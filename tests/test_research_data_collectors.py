from datetime import date
import sys

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.storage.db import Database


def test_cninfo_announcement_collector_syncs_incrementally(tmp_path):
    try:
        from sentinel.web.services.research_data_collectors import (
            CNInfoAnnouncementCollector,
        )
    except ImportError:
        pytest.fail("research data collectors are not implemented")

    calls = {"announcements": 0}

    def fake_post_json(_url, payload):
        if payload.get("stock") and not payload.get("category"):
            return {
                "stockList": [
                    {"code": "600519", "orgId": "gssh0600519", "zwjc": "贵州茅台"}
                ]
            }
        calls["announcements"] += 1
        return {
            "announcements": [
                {
                    "announcementId": "1001",
                    "announcementTitle": "2025 年年度报告",
                    "announcementTime": 1772121600000,
                    "adjunctUrl": "finalpage/2026-02-28/1001.PDF",
                },
                {
                    "announcementId": "1002",
                    "announcementTitle": "2026 年第一季度报告",
                    "announcementTime": 1777392000000,
                    "adjunctUrl": "finalpage/2026-04-30/1002.PDF",
                },
            ]
        }

    collector = CNInfoAnnouncementCollector(
        storage_dir=tmp_path / "cninfo",
        post_json=fake_post_json,
    )

    first = collector.sync_stock("600519", categories=["category_ndbg_szsh"])
    second = collector.sync_stock("600519", categories=["category_ndbg_szsh"])

    assert first.row_count == 2
    assert first.watermark == "1002"
    assert second.row_count == 0
    assert second.watermark == "1002"
    assert calls["announcements"] == 2

    stored = (tmp_path / "cninfo" / "600519.jsonl").read_text(encoding="utf-8")
    assert "2025 年年度报告" in stored
    assert "2026 年第一季度报告" in stored


def test_cninfo_announcement_collector_accepts_list_search_response(tmp_path):
    try:
        from sentinel.web.services.research_data_collectors import (
            CNInfoAnnouncementCollector,
        )
    except ImportError:
        pytest.fail("research data collectors are not implemented")

    def fake_post_json(_url, payload):
        if payload.get("stock") and not payload.get("category"):
            return [{"code": "600519", "orgId": "gssh0600519"}]
        return {"announcements": []}

    collector = CNInfoAnnouncementCollector(
        storage_dir=tmp_path / "cninfo",
        post_json=fake_post_json,
    )

    result = collector.sync_stock("600519", categories=["category_ndbg_szsh"])

    assert result.row_count == 0
    assert result.watermark is None


def test_cninfo_announcement_collector_classifies_risk_buckets(tmp_path):
    try:
        from sentinel.web.services.research_data_collectors import (
            CNInfoAnnouncementCollector,
        )
    except ImportError:
        pytest.fail("research data collectors are not implemented")

    def fake_post_json(_url, payload):
        if payload.get("stock") and not payload.get("category"):
            return {"stockList": [{"code": "600519", "orgId": "gssh0600519"}]}
        return {
            "announcements": [
                {
                    "announcementId": "2001",
                    "announcementTitle": "关于收到行政处罚决定书的公告",
                    "announcementTime": 1777392000000,
                },
                {
                    "announcementId": "2002",
                    "announcementTitle": "关于重大诉讼进展的公告",
                    "announcementTime": 1777392000000,
                },
                {
                    "announcementId": "2003",
                    "announcementTitle": "关于控股股东部分股份质押的公告",
                    "announcementTime": 1777392000000,
                },
                {
                    "announcementId": "2004",
                    "announcementTitle": "2025 年年度报告",
                    "announcementTime": 1772121600000,
                },
                {
                    "announcementId": "2005",
                    "announcementTitle": "关于回购公司股份方案的公告",
                    "announcementTime": 1777392000000,
                },
            ]
        }

    collector = CNInfoAnnouncementCollector(
        storage_dir=tmp_path / "cninfo",
        post_json=fake_post_json,
    )

    result = collector.sync_stock("600519", categories=["all"])

    assert result.classification_counts["regulatory_penalty"] == 1
    assert result.classification_counts["litigation"] == 1
    assert result.classification_counts["pledge"] == 1
    assert result.classification_counts["periodic_report"] == 1
    assert result.classification_counts["buyback"] == 1
    assert result.risk_count == 3
    assert [record["risk_level"] for record in result.risk_records] == [
        "high",
        "medium",
        "medium",
    ]


def test_a_share_evidence_collector_writes_metrics_and_audit(settings):
    try:
        from sentinel.web.services.research_data_collectors import (
            AShareEvidenceCollector,
        )
    except ImportError:
        pytest.fail("research data collectors are not implemented")

    class FakeProvider:
        def financial_indicators(self, symbol: str):
            assert symbol == "600519"
            return [
                {
                    "报告期": "2025-12-31",
                    "净资产收益率(%)": 24.5,
                    "销售毛利率(%)": 82.0,
                    "研发费用率(%)": 1.2,
                    "资产负债率(%)": 23.0,
                    "商誉占总资产比例(%)": 0.1,
                    "经营现金流量净额/净利润": 1.18,
                }
            ]

        def governance_events(self, symbol: str):
            assert symbol == "600519"
            return [{"event": "no_material_governance_alert"}]

    aggregator = MetricsAggregator(Database(settings.database_path))
    aggregator.bootstrap()
    collector = AShareEvidenceCollector(aggregator=aggregator, provider=FakeProvider())

    result = collector.collect(
        symbol="600519",
        market="A_SHARE",
        as_of=date(2026, 4, 30),
    )

    assert result.inserted_metric_count == 6
    assert result.trend_count == 3
    assert result.safety_count == 3
    assert set(result.metric_names) == {
        "roic_sustainability",
        "gmoat_stability",
        "rd_efficiency",
        "debt_ratio_deterioration",
        "goodwill_ratio",
        "operating_cashflow_ratio",
    }

    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    assert aggregator.get_latest_trend_metric(target, "roic_sustainability") is not None
    assert aggregator.get_latest_safety_metric(target, "operating_cashflow_ratio") is not None

    audit_rows = aggregator.get_metric_source_audit(target)
    assert len(audit_rows) == 6
    assert {row["source"] for row in audit_rows} == {"akshare_financial_indicators"}
    assert {row["as_of"] for row in audit_rows} == {date(2026, 4, 30)}


def test_akshare_provider_uses_recent_window_for_legacy_indicator(monkeypatch):
    try:
        from sentinel.web.services.research_data_collectors import AkShareAStockProvider
    except ImportError:
        pytest.fail("research data collectors are not implemented")

    calls = []

    class FakeAkshare:
        def stock_financial_analysis_indicator(self, **kwargs):
            calls.append(("legacy", kwargs))
            return [{"报告期": "2025-12-31", "净资产收益率(%)": 20.0}]

        def stock_financial_analysis_indicator_em(self, **kwargs):
            calls.append(("em", kwargs))
            return []

        def stock_financial_abstract_ths(self, **kwargs):
            calls.append(("ths", kwargs))
            return []

    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare())

    rows = AkShareAStockProvider().financial_indicators("600519")

    assert rows == [{"报告期": "2025-12-31", "净资产收益率(%)": 20.0}]
    assert calls[0][0] == "legacy"
    assert "start_year" in calls[0][1]

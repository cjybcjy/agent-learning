from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from sentinel.web.main import create_app
from sentinel.web.services.serenity_verification_service import (
    SerenityEvidenceGap,
    SerenityMetricTarget,
    SerenityVerificationPlan,
)


def test_serenity_verification_route_renders_source_and_metric_plan(monkeypatch):
    plan = SerenityVerificationPlan(
        symbol="600519",
        market="A_SHARE",
        company_name="贵州茅台",
        sector="白酒",
        boundary="read_only_verification_plan",
        summary="先补证据字段，再补动态指标。",
        evidence_gaps=[
            SerenityEvidenceGap(
                dimension="brand_premium",
                label="品牌溢价",
                missing_fields=["source", "as_of", "confidence", "bear_case"],
                source_paths=["年报/半年报/季报", "互动易/业绩说明会"],
                verification_items=["渠道库存与批价反向验证"],
                config_patch_hint="companies.600519.base_score.brand_premium 补 source/as_of/confidence/bear_case",
            )
        ],
        metric_targets=[
            SerenityMetricTarget(
                metric_name="operating_cashflow_ratio",
                target_table="safety_metrics",
                source_paths=["现金流量表"],
                financial_items=["经营活动现金流量净额", "净利润"],
                calculation_hint="经营现金流/净利润",
                reason="验证利润是否能转成现金。",
            )
        ],
        next_actions=["重新运行 MGFS 评估"],
        limitations=["不自动写入配置或数据库"],
    )

    class FakeService:
        def build_plan(self, **kwargs):
            return plan

    monkeypatch.setattr(
        "sentinel.web.routers.research._get_serenity_verification_service",
        lambda: FakeService(),
    )

    response = TestClient(create_app()).post(
        "/api/serenity-verification-plan",
        data={"symbol": "600519", "market": "A_SHARE"},
    )

    assert response.status_code == 200
    assert "Serenity 补证据路线图" in response.text
    assert "不自动写入配置" in response.text
    assert "品牌溢价" in response.text
    assert "source/as_of/confidence/bear_case" in response.text
    assert "operating_cashflow_ratio" in response.text
    assert "经营活动现金流量净额" in response.text
    assert 'hx-post="/api/serenity-metric-backfill"' in response.text
    assert 'name="metric_operating_cashflow_ratio"' in response.text


def test_serenity_metric_backfill_route_calls_service_and_resets_runtime(monkeypatch):
    calls = {}

    class FakeBackfillService:
        def backfill(self, **kwargs):
            calls["kwargs"] = kwargs
            return SimpleNamespace(
                symbol=kwargs["symbol"],
                market=kwargs["market"],
                inserted_count=2,
                trend_count=1,
                safety_count=1,
                recorded_at=datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc),
                metric_names=["roic_sustainability", "operating_cashflow_ratio"],
            )

    reset_calls = []
    monkeypatch.setattr(
        "sentinel.web.routers.research._get_serenity_metric_backfill_service",
        lambda: FakeBackfillService(),
        raising=False,
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research._reset_runtime_services_after_metric_backfill",
        lambda: reset_calls.append("reset"),
        raising=False,
    )

    response = TestClient(create_app()).post(
        "/api/serenity-metric-backfill",
        data={
            "symbol": "600519",
            "market": "A_SHARE",
            "source": "年报手动核验",
            "as_of": "2026-05-01",
            "metric_roic_sustainability": "84",
            "metric_operating_cashflow_ratio": "88",
        },
    )

    assert response.status_code == 200
    assert "已回填 2 项动态指标" in response.text
    assert calls["kwargs"]["symbol"] == "600519"
    assert calls["kwargs"]["market"] == "A_SHARE"
    assert calls["kwargs"]["values"] == {
        "roic_sustainability": 84.0,
        "operating_cashflow_ratio": 88.0,
    }
    assert calls["kwargs"]["source"] == "年报手动核验"
    assert calls["kwargs"]["as_of"] == date(2026, 5, 1)
    assert reset_calls == ["reset"]

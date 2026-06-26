from types import SimpleNamespace

from sentinel.web.services.research_data_collectors import CNInfoSyncResult
from sentinel.web.services.research_data_task_service import ResearchDataTaskService


def test_research_data_task_service_runs_selected_announcement_task_only(tmp_path, settings):
    calls = {"announcement_categories": []}

    class FakeAnnouncementCollector:
        def sync_stock(self, symbol, *, categories=None):
            calls["symbol"] = symbol
            calls["announcement_categories"].append(tuple(categories or []))
            return CNInfoSyncResult(
                symbol=symbol,
                row_count=3,
                watermark="2003",
                records=[],
                storage_path=tmp_path / "600519.jsonl",
                classification_counts={"regulatory_penalty": 1, "litigation": 1},
                risk_count=2,
                risk_records=[
                    {
                        "title": "关于收到行政处罚决定书的公告",
                        "risk_level": "high",
                    },
                    {
                        "title": "关于重大诉讼进展的公告",
                        "risk_level": "medium",
                    },
                ],
            )

    class FakeEvidenceCollector:
        def collect(self, **kwargs):
            raise AssertionError("financial metrics should not run")

    service = ResearchDataTaskService(
        database_path=settings.database_path,
        announcement_collector=FakeAnnouncementCollector(),
        evidence_collector=FakeEvidenceCollector(),
    )

    result = service.fill_gaps(
        symbol="600519",
        market="A_SHARE",
        task_keys=["risk_announcements"],
    )

    assert result.task_keys == ["risk_announcements"]
    assert result.announcement_count == 3
    assert result.risk_announcement_count == 2
    assert result.inserted_metric_count == 0
    assert result.task_results[0].label == "巨潮风险公告核验"
    assert result.task_results[0].summary == "发现 2 条风险公告"
    assert calls["announcement_categories"] == [
        (
            "category_jjgg_szsh",
            "category_bcgz_szsh",
            "category_gddh_szsh",
        )
    ]

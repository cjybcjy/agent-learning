from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_research_data_fill_gaps_route_executes_task_and_resets_runtime(monkeypatch):
    calls = {}

    class FakeResearchDataTaskService:
        def fill_gaps(self, *, symbol: str, market: str):
            calls["args"] = {"symbol": symbol, "market": market}
            return SimpleNamespace(
                symbol=symbol,
                market=market,
                inserted_metric_count=6,
                trend_count=3,
                safety_count=3,
                announcement_count=2,
                risk_announcement_count=1,
                metric_names=["roic_sustainability", "operating_cashflow_ratio"],
                warnings=[],
                task_keys=["risk_announcements", "financial_metrics"],
                task_results=[
                    SimpleNamespace(
                        task_key="risk_announcements",
                        label="巨潮风险公告核验",
                        status="success",
                        summary="发现 1 条风险公告",
                    )
                ],
                topics=[
                    SimpleNamespace(
                        topic="cninfo:600519:announcements",
                        label="巨潮公告",
                        status="success",
                        row_count=2,
                        watermark="1002",
                        source="cninfo",
                        error="",
                    ),
                    SimpleNamespace(
                        topic="ashare:600519:financials",
                        label="财务指标",
                        status="success",
                        row_count=6,
                        watermark="2026-04-30",
                        source="akshare",
                        error="",
                    ),
                ],
                hub_snapshot=[
                    SimpleNamespace(
                        topic="ashare:600519:financials",
                        status="success",
                        row_count=6,
                        watermark="2026-04-30",
                        source="akshare",
                        last_error="",
                    )
                ],
                executed_at=datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc),
            )

    reset_calls = []
    monkeypatch.setattr(
        "sentinel.web.routers.research._get_research_data_task_service",
        lambda: FakeResearchDataTaskService(),
        raising=False,
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research._reset_runtime_services_after_metric_backfill",
        lambda: reset_calls.append("reset"),
        raising=False,
    )

    response = TestClient(create_app()).post(
        "/api/research-data/fill-gaps",
        data={"symbol": "600519", "market": "A_SHARE"},
    )

    assert response.status_code == 200
    assert calls["args"] == {"symbol": "600519", "market": "A_SHARE"}
    assert reset_calls == ["reset"]
    assert "补数据执行结果" in response.text
    assert "ResearchDataHub" in response.text
    assert "巨潮公告" in response.text
    assert "财务指标" in response.text
    assert "巨潮风险公告核验" in response.text
    assert "roic_sustainability" in response.text


def test_research_data_fill_gaps_route_passes_selected_task_keys(monkeypatch):
    calls = {}

    class FakeResearchDataTaskService:
        def fill_gaps(self, *, symbol: str, market: str, task_keys=None):
            calls["args"] = {
                "symbol": symbol,
                "market": market,
                "task_keys": task_keys,
            }
            return SimpleNamespace(
                symbol=symbol,
                market=market,
                inserted_metric_count=0,
                trend_count=0,
                safety_count=0,
                announcement_count=3,
                risk_announcement_count=2,
                metric_names=[],
                warnings=[],
                task_keys=task_keys,
                task_results=[
                    SimpleNamespace(
                        task_key="risk_announcements",
                        label="巨潮风险公告核验",
                        status="success",
                        summary="发现 2 条风险公告",
                    )
                ],
                topics=[],
                hub_snapshot=[],
                executed_at=datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc),
            )

    monkeypatch.setattr(
        "sentinel.web.routers.research._get_research_data_task_service",
        lambda: FakeResearchDataTaskService(),
        raising=False,
    )

    response = TestClient(create_app()).post(
        "/api/research-data/fill-gaps",
        data={
            "symbol": "600519",
            "market": "A_SHARE",
            "task_keys": ["risk_announcements", "periodic_reports"],
        },
    )

    assert response.status_code == 200
    assert calls["args"] == {
        "symbol": "600519",
        "market": "A_SHARE",
        "task_keys": ["risk_announcements", "periodic_reports"],
    }
    assert "发现 2 条风险公告" in response.text

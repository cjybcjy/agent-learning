from fastapi.testclient import TestClient
from unittest.mock import patch

from sentinel.web.services.candidate_discovery_service import (
    BoardEvidence,
    CandidateDiscoveryResult,
    DiscoveredCandidate,
)
from sentinel.web.main import create_app
from sentinel.web.services.scan_service import create_task, get_task, run_scan_task
from sentinel.mgfs.scanner import ScanResult


def test_scan_start_returns_task_id():
    client = TestClient(create_app())
    response = client.post("/api/scan/start", data={"theme": "Consumer_Staples"})
    assert response.status_code == 200
    assert "scan-task-id" in response.text


def test_scan_start_passes_fund_rank_limit_to_background_task():
    client = TestClient(create_app())
    with patch("sentinel.web.routers.research.run_scan_task") as mock_run:
        response = client.post(
            "/api/scan/start",
            data={
                "theme": "Self_Reliant_Semiconductors",
                "fund_rank_limit": "20",
            },
        )

    assert response.status_code == 200
    assert mock_run.call_args.args[3] == "neutral"
    assert mock_run.call_args.args[4] == 20


def test_candidate_discovery_route_renders_objective_evidence():
    client = TestClient(create_app())
    result = CandidateDiscoveryResult(
        theme_key="Embodied_Robotics",
        theme_label="机器人与具身智能",
        search_terms=["机器人", "减速器"],
        matched_board_count=2,
        source_mix={"concept": 2, "industry": 0},
        candidates=[
            DiscoveredCandidate(
                symbol="300024",
                name="机器人",
                evidence=[
                    BoardEvidence(
                        source="concept",
                        board_name="机器人概念",
                        board_code="BK0001",
                        matched_terms=["机器人"],
                    )
                ],
                in_static_pool=True,
                static_theme="Embodied_Robotics",
                fund_heavy_holding_count=11,
            )
        ],
    )

    with patch("sentinel.web.routers.research.CandidateDiscoveryService") as service_cls:
        service_cls.return_value.discover_theme.return_value = result
        response = client.post(
            "/api/candidates/discover",
            data={"theme": "Embodied_Robotics"},
        )

    assert response.status_code == 200
    assert "客观候选发现" in response.text
    assert "机器人概念" in response.text
    assert "300024" in response.text
    service_cls.return_value.discover_theme.assert_called_once_with("Embodied_Robotics")


def test_candidate_discovery_route_handles_missing_theme_visibly():
    client = TestClient(create_app())

    response = client.post("/api/candidates/discover", data={})

    assert response.status_code == 200
    assert "请先选择宏观主题" in response.text


def test_run_scan_task_sets_candidate_total_before_evaluation():
    task_id = create_task("Embodied_Robotics")

    class FakeScanner:
        def preview_theme(
            self,
            *,
            theme_name: str,
            target_roles: list[str] | None,
            fund_rank_limit: int | None,
        ) -> dict:
            return {
                "total_candidates": 10,
                "evaluated": 8,
                "skipped_by_role": 1,
                "skipped_by_fund_rank": 1,
                "fund_rank_limit": fund_rank_limit,
            }

        def scan_theme(self, **kwargs) -> ScanResult:
            task = get_task(task_id)
            assert task is not None
            assert task.total == 10
            assert task.summary["evaluated"] == 8
            return ScanResult(
                theme=kwargs["theme_name"],
                total_candidates=10,
                filtered_count=0,
                reports=[],
                summary={
                    "total_candidates": 10,
                    "evaluated": 8,
                    "passed_all_gates": 0,
                    "skipped_by_role": 1,
                    "skipped_by_fund_rank": 1,
                    "fund_rank_limit": fund_rank_limit,
                    "skipped_by_moat": 0,
                    "skipped_by_veto": 0,
                    "skipped_by_zone": 8,
                },
            )

    fund_rank_limit = 8
    with patch("sentinel.web.services.scan_service.get_scanner", return_value=FakeScanner()):
        run_scan_task(
            task_id,
            "Embodied_Robotics",
            target_roles=["upstream_resource"],
            policy_rating="neutral",
            fund_rank_limit=fund_rank_limit,
        )

    task = get_task(task_id)
    assert task is not None
    assert task.status.value == "completed"
    assert task.total == 10
    assert task.completed == 0

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sentinel.web.services.pipeline_service import PipelineService


def test_pipeline_core_calls_stop_loss_monitor_after_scan():
    """Pipeline execution should scan active holdings for stop-loss triggers."""
    with patch("sentinel.web.services.pipeline_service._get_repository") as mock_repo:
        repo = MagicMock()
        repo.list_pipeline_batches.return_value = []
        repo.get_pipeline_results.return_value = []
        repo.list_active_holdings.return_value = [
            {
                "symbol": "600690",
                "name": "海尔智家",
                "sector": "家电",
                "entry_price": 100.0,
                "current_price": 79.0,
                "highest_price": 100.0,
                "weight": 0.15,
                "stop_loss_hard": -0.20,
                "stop_loss_trailing": -0.15,
                "portfolio_stop_loss": -0.10,
            }
        ]
        mock_repo.return_value = repo

        with patch("sentinel.web.services.pipeline_service.get_orchestrator") as mock_orch:
            orch = MagicMock()
            decision = MagicMock()
            decision.rating = "Hold"
            decision.action = "观望"
            decision.final_score = 70.0
            decision.factor_scores = {}
            orch.evaluate.return_value = decision
            mock_orch.return_value = orch

            with patch("sentinel.web.services.pipeline_service.MGFSRepository") as mock_repo_cls:
                mock_repo_cls.return_value = repo

                svc = PipelineService()
                batch_id = svc.create_batch()

                with patch.object(svc, "_run_stop_loss_scan") as mock_scan:
                    svc._execute_pipeline_core(batch_id)
                    mock_scan.assert_called_once()

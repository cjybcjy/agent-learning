from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sentinel.mgfs.orchestrator import InvestmentDecision
from sentinel.mgfs.factor_plugin import FactorScore, TargetInfo
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
from sentinel.config import AppSettings
from sentinel.storage.db import Database
from sentinel.web.services.pipeline_service import PipelineService


@pytest.fixture
def repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        repository = MGFSRepository(db)
        repository.bootstrap()
        yield repository


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    return orch


class FakeDecision:
    def __init__(self, symbol: str, rating: str, final_score: float) -> None:
        self.target = TargetInfo(symbol=symbol, market=MagicMock(), asset_class="equity", name=symbol)
        self.rating = rating
        self.action = "test"
        self.final_score = final_score
        self.factor_scores = {
            "moat": FactorScore(factor_key="moat", factor_name="护城河", score=80.0, weight=0.5, details={"percentile": 15.0}),
            "valuation": FactorScore(factor_key="valuation", factor_name="估值", score=70.0, weight=0.3, details={"primary_percentile": 20.0}),
            "timing": FactorScore(factor_key="timing", factor_name="择时", score=60.0, weight=0.1, details={}),
        }


class TestPipelineServiceTrigger:
    def test_create_batch_creates_running_record(self, repo: MGFSRepository, mock_orchestrator: Any) -> None:
        svc = PipelineService(orchestrator=mock_orchestrator, repository=repo)
        batch_id = svc.create_batch()

        assert batch_id.startswith("B_")
        batch = repo.get_pipeline_batch(batch_id)
        assert batch is not None
        assert batch["status"] == "running"

    def test_run_pipeline_executes_in_background(self, repo: MGFSRepository, mock_orchestrator: Any) -> None:
        svc = PipelineService(orchestrator=mock_orchestrator, repository=repo)
        batch_id = "B_20260518_120000"
        repo.create_pipeline_batch(batch_id, "running")

        mock_orchestrator.evaluate.return_value = FakeDecision("600519", "Strong Buy", 90.0)
        with patch.object(svc, "_load_stock_pool", return_value=[
            TargetInfo(symbol="600519", market=MagicMock(), asset_class="equity")
        ]):
            svc.run_pipeline(batch_id)

        batch = repo.get_pipeline_batch(batch_id)
        assert batch["status"] == "completed"

    def test_load_stock_pool_preserves_moat_metadata(self, tmp_path, monkeypatch) -> None:
        config_dir = tmp_path / "config"
        data_dir = tmp_path / "data"
        config_dir.mkdir()
        data_dir.mkdir()
        (config_dir / "moat_static_base.yaml").write_text(
            """
companies:
  "600519":
    name: "贵州茅台"
    sector: "白酒"
    theme: "Consumer_Staples"
    ecosystem_role: "downstream_app"
    base_score: {}
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "sentinel.web.services.pipeline_service.settings",
            AppSettings(base_dir=tmp_path, config_dir=config_dir, data_dir=data_dir),
        )

        targets = PipelineService(orchestrator=MagicMock(), repository=MagicMock())._load_stock_pool()

        assert len(targets) == 1
        assert targets[0].name == "贵州茅台"
        assert targets[0].sector == "白酒"
        assert targets[0].theme == "Consumer_Staples"
        assert targets[0].ecosystem_role == "downstream_app"


class TestPipelineServiceExecute:
    def test_run_pipeline_saves_results(self, repo: MGFSRepository, mock_orchestrator: Any) -> None:
        svc = PipelineService(orchestrator=mock_orchestrator, repository=repo)
        batch_id = "B_20260518_120000"
        repo.create_pipeline_batch(batch_id, "running")

        mock_orchestrator.evaluate.return_value = FakeDecision("600519", "Strong Buy", 90.0)

        with patch.object(svc, "_load_stock_pool", return_value=[
            TargetInfo(symbol="600519", market=MagicMock(), asset_class="equity")
        ]):
            svc.run_pipeline(batch_id)

        batch = repo.get_pipeline_batch(batch_id)
        assert batch["status"] == "completed"
        assert batch["total_count"] == 1
        assert batch["strong_buy_count"] == 1

        results = repo.get_pipeline_results(batch_id)
        assert len(results) == 1
        assert results[0]["symbol"] == "600519"
        assert results[0]["final_score"] == 90.0

    def test_run_pipeline_skips_failed_symbol(self, repo: MGFSRepository, mock_orchestrator: Any) -> None:
        svc = PipelineService(orchestrator=mock_orchestrator, repository=repo)
        batch_id = "B_20260518_120000"
        repo.create_pipeline_batch(batch_id, "running")

        mock_orchestrator.evaluate.side_effect = Exception("network error")

        with patch.object(svc, "_load_stock_pool", return_value=[
            TargetInfo(symbol="600519", market=MagicMock(), asset_class="equity")
        ]):
            svc.run_pipeline(batch_id)

        # Single symbol failure should be skipped, batch still completed with 0 results
        batch = repo.get_pipeline_batch(batch_id)
        assert batch["status"] == "completed"
        assert batch["total_count"] == 1
        results = repo.get_pipeline_results(batch_id)
        assert results == []

    def test_run_pipeline_system_failure(self, repo: MGFSRepository, mock_orchestrator: Any) -> None:
        svc = PipelineService(orchestrator=mock_orchestrator, repository=repo)
        batch_id = "B_20260518_120000"
        repo.create_pipeline_batch(batch_id, "running")

        with patch.object(svc, "_load_stock_pool", side_effect=Exception("config corrupt")):
            svc.run_pipeline(batch_id)

        batch = repo.get_pipeline_batch(batch_id)
        assert batch["status"] == "failed"
        assert "config corrupt" in batch["error_log"]


class TestPipelineServiceExport:
    def test_export_csv_returns_data(self, repo: MGFSRepository) -> None:
        svc = PipelineService(orchestrator=MagicMock(), repository=repo)
        repo.create_pipeline_batch("B_20260518_120000", "completed")
        repo.save_pipeline_result(
            batch_id="B_20260518_120000",
            symbol="600519",
            name="贵州茅台",
            moat_score=80.5,
            valuation_percentile=15.2,
            timing_score=45.0,
            final_score=75.3,
            rating="Accumulate",
            action="分批建仓",
        )

        csv_content = svc.export_csv("B_20260518_120000")
        assert "600519" in csv_content
        assert "贵州茅台" in csv_content
        assert "Accumulate" in csv_content

    def test_export_csv_empty_batch(self, repo: MGFSRepository) -> None:
        svc = PipelineService(orchestrator=MagicMock(), repository=repo)
        repo.create_pipeline_batch("B_20260518_120000", "completed")

        csv_content = svc.export_csv("B_20260518_120000")
        assert "symbol" in csv_content  # header present
        assert "600519" not in csv_content


class TestPipelineServiceResults:
    def test_get_pipeline_results_enriches_symbol_only_names(
        self, repo: MGFSRepository, tmp_path, monkeypatch
    ) -> None:
        config_dir = tmp_path / "config"
        data_dir = tmp_path / "data"
        config_dir.mkdir()
        data_dir.mkdir()
        (config_dir / "moat_static_base.yaml").write_text(
            """
companies:
  "600519":
    name: "贵州茅台"
    base_score: {}
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "sentinel.web.services.pipeline_service.settings",
            AppSettings(base_dir=tmp_path, config_dir=config_dir, data_dir=data_dir),
        )

        repo.create_pipeline_batch("B_20260518_120000", "completed")
        repo.save_pipeline_result(
            batch_id="B_20260518_120000",
            symbol="600519",
            name="600519",
            moat_score=80.5,
            valuation_percentile=15.2,
            timing_score=45.0,
            final_score=75.3,
            rating="Accumulate",
            action="分批建仓",
        )

        rows = PipelineService(orchestrator=MagicMock(), repository=repo).get_pipeline_results(
            "B_20260518_120000"
        )

        assert rows[0]["name"] == "贵州茅台"


class TestPipelineServiceHistory:
    def test_get_history_returns_batches(self, repo: MGFSRepository) -> None:
        svc = PipelineService(orchestrator=MagicMock(), repository=repo)
        repo.create_pipeline_batch("B_20260518_100000", "completed")
        repo.create_pipeline_batch("B_20260518_110000", "completed")

        history = svc.get_history(limit=10)
        assert len(history) == 2

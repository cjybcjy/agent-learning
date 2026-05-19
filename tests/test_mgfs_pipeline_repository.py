from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
from sentinel.storage.db import Database


@pytest.fixture
def repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        repository = MGFSRepository(db)
        repository.bootstrap()
        yield repository


class TestPipelineBatch:
    def test_create_batch(self, repo: MGFSRepository) -> None:
        repo.create_pipeline_batch("B_20260518_120000", "running")
        batch = repo.get_pipeline_batch("B_20260518_120000")
        assert batch is not None
        assert batch["batch_id"] == "B_20260518_120000"
        assert batch["status"] == "running"
        assert batch["total_count"] == 0
        assert batch["strong_buy_count"] == 0

    def test_update_batch_status_completed(self, repo: MGFSRepository) -> None:
        repo.create_pipeline_batch("B_20260518_120000", "running")
        repo.update_pipeline_batch_status(
            "B_20260518_120000",
            status="completed",
            total_count=50,
            strong_buy_count=3,
        )
        batch = repo.get_pipeline_batch("B_20260518_120000")
        assert batch["status"] == "completed"
        assert batch["total_count"] == 50
        assert batch["strong_buy_count"] == 3

    def test_update_batch_status_failed(self, repo: MGFSRepository) -> None:
        repo.create_pipeline_batch("B_20260518_120000", "running")
        repo.update_pipeline_batch_status(
            "B_20260518_120000",
            status="failed",
            error_log="connection timeout",
        )
        batch = repo.get_pipeline_batch("B_20260518_120000")
        assert batch["status"] == "failed"
        assert batch["error_log"] == "connection timeout"

    def test_get_nonexistent_batch_returns_none(self, repo: MGFSRepository) -> None:
        assert repo.get_pipeline_batch("NONEXISTENT") is None

    def test_list_batch_history(self, repo: MGFSRepository) -> None:
        repo.create_pipeline_batch("B_20260518_100000", "completed")
        repo.create_pipeline_batch("B_20260518_110000", "completed")
        repo.create_pipeline_batch("B_20260518_120000", "running")

        history = repo.list_pipeline_batches(limit=10)
        assert len(history) == 3
        # Ordered by triggered_at DESC
        assert history[0]["batch_id"] == "B_20260518_120000"

    def test_list_batch_history_with_limit(self, repo: MGFSRepository) -> None:
        for i in range(5):
            repo.create_pipeline_batch(f"B_20260518_{i:02d}0000", "completed")

        history = repo.list_pipeline_batches(limit=3)
        assert len(history) == 3


class TestPipelineResult:
    def test_save_and_get_result(self, repo: MGFSRepository) -> None:
        repo.create_pipeline_batch("B_20260518_120000", "running")
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
        results = repo.get_pipeline_results("B_20260518_120000")
        assert len(results) == 1
        assert results[0]["symbol"] == "600519"
        assert results[0]["name"] == "贵州茅台"
        assert results[0]["final_score"] == 75.3

    def test_get_results_for_nonexistent_batch(self, repo: MGFSRepository) -> None:
        results = repo.get_pipeline_results("NONEXISTENT")
        assert results == []

    def test_save_multiple_results(self, repo: MGFSRepository) -> None:
        repo.create_pipeline_batch("B_20260518_120000", "running")
        for sym, score in [("600519", 80.0), ("000001", 65.0), ("300750", 90.0)]:
            repo.save_pipeline_result(
                batch_id="B_20260518_120000",
                symbol=sym,
                name=sym,
                moat_score=score,
                valuation_percentile=20.0,
                timing_score=50.0,
                final_score=score,
                rating="Hold",
                action="等待",
            )
        results = repo.get_pipeline_results("B_20260518_120000")
        assert len(results) == 3

    def test_result_foreign_key_constraint(self, repo: MGFSRepository) -> None:
        with pytest.raises(Exception):
            repo.save_pipeline_result(
                batch_id="NONEXISTENT",
                symbol="600519",
                name="Test",
                moat_score=50.0,
                valuation_percentile=50.0,
                timing_score=50.0,
                final_score=50.0,
                rating="Hold",
                action="等待",
            )

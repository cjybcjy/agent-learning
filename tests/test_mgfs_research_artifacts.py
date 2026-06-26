from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path

from sentinel.mgfs.evolution.research_artifacts import write_backtest_research_artifacts


def test_write_backtest_research_artifacts_generates_validated_run_dir(tmp_path: Path):
    days = [date(2026, 6, 1) + timedelta(days=i) for i in range(5)]
    price_loaders = {
        "300750": {day: 100.0 + index for index, day in enumerate(days)},
    }

    report = write_backtest_research_artifacts(
        run_dir=tmp_path / "mgfs_backtest_research",
        symbols=["300750"],
        names={"300750": "宁德时代"},
        static_scores={"300750": 86.0},
        price_loaders=price_loaders,
        start_date=days[0],
        end_date=days[-1],
        config_hash="config-hash",
        external_signal_hash="external-signal-hash",
    )

    run_dir = tmp_path / "mgfs_backtest_research"
    assert report.passed is True
    assert (run_dir / "decision_inputs.jsonl").exists()
    assert (run_dir / "mgfs_research_signal_v1.jsonl").exists()
    assert (run_dir / "agent_discussion.md").exists()
    assert (run_dir / "run_validation_report.json").exists()

    decision = json.loads((run_dir / "decision_inputs.jsonl").read_text(encoding="utf-8").strip())
    signal = json.loads((run_dir / "mgfs_research_signal_v1.jsonl").read_text(encoding="utf-8").strip())
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))

    assert decision["symbol"] == "300750"
    assert decision["as_of_date"] == days[-1].isoformat()
    assert decision["config_hash"] == "config-hash"
    assert decision["external_signal_hash"] == "external-signal-hash"
    assert decision["price_snapshot_hash"]
    assert decision["evidence_hashes"]
    assert signal["instruction_boundary"] == "research_only"
    assert signal["config_hash"] == decision["config_hash"]
    assert signal["price_snapshot_hash"] == decision["price_snapshot_hash"]
    assert summary["adapter_status"]["point_in_time_inputs"] == "enabled"

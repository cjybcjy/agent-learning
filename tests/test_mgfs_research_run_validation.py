from __future__ import annotations

import json
from pathlib import Path

from sentinel.mgfs.evolution.research_run_validation import validate_mgfs_research_run


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _valid_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "mgfs_research_run_valid"
    run_dir.mkdir()
    decisions = [
        {
            "symbol": "300750",
            "name": "宁德时代",
            "as_of_date": "2026-06-20",
            "config_hash": "config-hash",
            "external_signal_hash": "external-signal-hash",
            "price_snapshot_hash": "price-hash",
            "evidence_hashes": ["event-hash"],
        }
    ]
    signals = [
        {
            "schema_version": "mgfs_research_signal_v1",
            "symbol": "300750",
            "name": "宁德时代",
            "as_of_date": "2026-06-20",
            "action_hint": "increase_attention",
            "score": 0.36,
            "confidence": 0.7,
            "rationale": "护城河证据仍然支持核心池观察。",
            "evidence_hashes": ["event-hash"],
            "source_scores": {"moat_agent": 0.6, "risk_agent": -0.2},
            "risk_flags": ["conflict"],
            "config_hash": "config-hash",
            "price_snapshot_hash": "price-hash",
            "expires_at": "2026-06-23",
            "instruction_boundary": "research_only",
        }
    ]
    _write_jsonl(run_dir / "decision_inputs.jsonl", decisions)
    _write_jsonl(run_dir / "mgfs_research_signal_v1.jsonl", signals)
    (run_dir / "agent_discussion.md").write_text("# 多 agent 讨论\n正反证据摘要\n", encoding="utf-8")
    _write_json(
        run_dir / "run_summary.json",
        {
            "ok": True,
            "run_id": "MGFS_20260620_001",
            "decision_count": 1,
            "symbol_count": 1,
            "adapter_status": {
                "point_in_time_inputs": "enabled",
                "research_signal_schema": "mgfs_research_signal_v1",
                "instruction_boundary": "research_only",
            },
            "borrowed_from": {
                "repo": "utopia",
                "patterns": [
                    "point_in_time_inputs",
                    "alpha_signal_jsonl",
                    "run_artifact_validation",
                ],
            },
        },
    )
    return run_dir


def test_validate_mgfs_research_run_accepts_complete_artifact(tmp_path: Path):
    report = validate_mgfs_research_run(_valid_run_dir(tmp_path), expected_symbols=["300750"])

    assert report.passed is True
    assert report.failures == []
    assert report.warnings == []


def test_validate_mgfs_research_run_rejects_missing_signal_evidence(tmp_path: Path):
    run_dir = _valid_run_dir(tmp_path)
    signal_path = run_dir / "mgfs_research_signal_v1.jsonl"
    signal = json.loads(signal_path.read_text(encoding="utf-8").strip())
    signal["evidence_hashes"] = []
    _write_jsonl(signal_path, [signal])

    report = validate_mgfs_research_run(run_dir, expected_symbols=["300750"])

    assert report.passed is False
    assert "signal[0] missing evidence_hashes" in report.failures


def test_validate_mgfs_research_run_rejects_missing_external_signal_hash(tmp_path: Path):
    run_dir = _valid_run_dir(tmp_path)
    decision_path = run_dir / "decision_inputs.jsonl"
    decision = json.loads(decision_path.read_text(encoding="utf-8").strip())
    decision.pop("external_signal_hash")
    _write_jsonl(decision_path, [decision])

    report = validate_mgfs_research_run(run_dir, expected_symbols=["300750"])

    assert report.passed is False
    assert "decision[0] missing external_signal_hash" in report.failures


def test_validate_mgfs_research_run_rejects_direct_trading_boundary(tmp_path: Path):
    run_dir = _valid_run_dir(tmp_path)
    signal_path = run_dir / "mgfs_research_signal_v1.jsonl"
    signal = json.loads(signal_path.read_text(encoding="utf-8").strip())
    signal["instruction_boundary"] = "trade_directive"
    _write_jsonl(signal_path, [signal])

    report = validate_mgfs_research_run(run_dir, expected_symbols=["300750"])

    assert report.passed is False
    assert "signal[0] instruction_boundary is not research_only" in report.failures

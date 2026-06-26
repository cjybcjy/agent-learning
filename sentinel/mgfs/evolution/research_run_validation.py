from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable

from sentinel.mgfs.evolution.research_signal import MGFSResearchSignalV1


@dataclass(frozen=True, slots=True)
class MGFSResearchRunValidationReport:
    run_dir: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, indent=2)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path} contained a non-object JSONL row")
        rows.append(payload)
    return rows


def _failure_if(condition: bool, message: str, failures: list[str]) -> None:
    if condition:
        failures.append(message)


def validate_mgfs_research_run(
    run_dir: str | Path,
    *,
    expected_symbols: Iterable[str] = (),
) -> MGFSResearchRunValidationReport:
    """Validate MGFS research-loop artifacts before trusting a backtest result."""

    path = Path(run_dir)
    failures: list[str] = []
    warnings: list[str] = []
    summary = _read_json(path / "run_summary.json")
    _failure_if(summary is None, "missing run_summary.json", failures)
    if summary is None:
        return MGFSResearchRunValidationReport(str(path), False, failures, warnings)

    _failure_if(summary.get("ok") is not True, "run_summary.ok is not true", failures)
    adapter_status = summary.get("adapter_status") or {}
    _failure_if(
        adapter_status.get("point_in_time_inputs") != "enabled",
        "point_in_time_inputs are not enabled",
        failures,
    )
    _failure_if(
        adapter_status.get("research_signal_schema") != "mgfs_research_signal_v1",
        "research_signal_schema is not mgfs_research_signal_v1",
        failures,
    )
    _failure_if(
        adapter_status.get("instruction_boundary") != "research_only",
        "instruction_boundary is not research_only",
        failures,
    )
    borrowed_from = summary.get("borrowed_from") or {}
    if borrowed_from.get("repo") != "utopia":
        warnings.append("run_summary.borrowed_from.repo is not utopia")

    decisions = _read_jsonl(path / "decision_inputs.jsonl")
    signals = _read_jsonl(path / "mgfs_research_signal_v1.jsonl")
    decision_count = int(summary.get("decision_count") or 0)
    _failure_if(not decisions, "missing decision_inputs.jsonl rows", failures)
    _failure_if(not signals, "missing mgfs_research_signal_v1.jsonl rows", failures)
    _failure_if(decision_count != len(decisions), "decision_count does not match decision input rows", failures)
    _failure_if(decision_count != len(signals), "decision_count does not match signal rows", failures)

    expected_symbol_set = {str(symbol) for symbol in expected_symbols}
    signal_symbols = {str(signal.get("symbol")) for signal in signals}
    for symbol in sorted(expected_symbol_set - signal_symbols):
        failures.append(f"missing expected symbol: {symbol}")

    decisions_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for index, decision in enumerate(decisions):
        symbol = str(decision.get("symbol") or "")
        as_of_date = str(decision.get("as_of_date") or "")
        decisions_by_key[(symbol, as_of_date)] = decision
        _failure_if(not symbol, f"decision[{index}] missing symbol", failures)
        _failure_if(not as_of_date, f"decision[{index}] missing as_of_date", failures)
        _failure_if(not decision.get("config_hash"), f"decision[{index}] missing config_hash", failures)
        _failure_if(
            not decision.get("external_signal_hash"),
            f"decision[{index}] missing external_signal_hash",
            failures,
        )
        _failure_if(not decision.get("price_snapshot_hash"), f"decision[{index}] missing price_snapshot_hash", failures)
        _failure_if(not decision.get("evidence_hashes"), f"decision[{index}] missing evidence_hashes", failures)

    for index, signal_payload in enumerate(signals):
        try:
            signal = MGFSResearchSignalV1.from_json(json.dumps(signal_payload, ensure_ascii=False))
        except Exception as exc:
            failures.append(f"signal[{index}] invalid schema: {exc}")
            continue
        _failure_if(not signal.evidence_hashes, f"signal[{index}] missing evidence_hashes", failures)
        _failure_if(not signal.source_scores, f"signal[{index}] missing source_scores", failures)
        _failure_if(
            signal.instruction_boundary != "research_only",
            f"signal[{index}] instruction_boundary is not research_only",
            failures,
        )
        decision = decisions_by_key.get((signal.symbol, signal.as_of_date))
        _failure_if(decision is None, f"signal[{index}] has no matching decision input", failures)
        if decision is None:
            continue
        _failure_if(
            signal.config_hash != decision.get("config_hash"),
            f"signal[{index}] config_hash does not match decision input",
            failures,
        )
        _failure_if(
            signal.price_snapshot_hash != decision.get("price_snapshot_hash"),
            f"signal[{index}] price_snapshot_hash does not match decision input",
            failures,
        )

    discussion_path = path / "agent_discussion.md"
    _failure_if(
        not discussion_path.exists() or discussion_path.stat().st_size == 0,
        "missing non-empty agent_discussion.md",
        failures,
    )

    return MGFSResearchRunValidationReport(str(path), not failures, failures, warnings)

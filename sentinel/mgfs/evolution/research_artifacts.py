from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from sentinel.mgfs.evolution.research_run_validation import (
    MGFSResearchRunValidationReport,
    validate_mgfs_research_run,
)
from sentinel.mgfs.evolution.research_signal import (
    MGFSAgentSignal,
    merge_mgfs_agent_signals,
)


def stable_json_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def file_content_hash(path: Path) -> str:
    if not path.exists():
        return stable_json_hash({"missing": str(path)})
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16]


def write_backtest_research_artifacts(
    *,
    run_dir: str | Path,
    symbols: list[str],
    names: Mapping[str, str],
    static_scores: Mapping[str, float],
    price_loaders: Mapping[str, Mapping[date, float]],
    start_date: date,
    end_date: date,
    config_hash: str,
    external_signal_hash: str,
) -> MGFSResearchRunValidationReport:
    """Write point-in-time MGFS research artifacts for a historical backtest."""

    output_dir = Path(run_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    decisions: list[dict[str, Any]] = []
    signal_lines: list[str] = []
    discussion_lines = [
        "# MGFS 历史回测研究证据\n\n",
        f"- 回测窗口: {start_date.isoformat()} -> {end_date.isoformat()}\n",
        "- 边界: research_only, 不生成买卖指令。\n",
    ]
    active_symbols = [symbol for symbol in symbols if symbol in price_loaders]

    for symbol in active_symbols:
        prices = price_loaders.get(symbol, {})
        ordered_prices = [
            {"date": day.isoformat(), "close": float(prices[day])}
            for day in sorted(prices)
            if start_date <= day <= end_date
        ]
        price_snapshot_hash = stable_json_hash(
            {
                "symbol": symbol,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "prices": ordered_prices,
            }
        )
        evidence_hash = stable_json_hash(
            {
                "symbol": symbol,
                "config_hash": config_hash,
                "external_signal_hash": external_signal_hash,
                "price_snapshot_hash": price_snapshot_hash,
                "as_of_date": end_date.isoformat(),
            }
        )
        name = names.get(symbol, symbol)
        static_score = float(static_scores.get(symbol, 50.0))
        normalized_score = max(-1.0, min(1.0, (static_score - 50.0) / 50.0))
        if normalized_score >= 0.2:
            action = "increase_attention"
        elif normalized_score <= -0.2:
            action = "reduce_attention"
        else:
            action = "hold_review"

        decisions.append(
            {
                "symbol": symbol,
                "name": name,
                "as_of_date": end_date.isoformat(),
                "config_hash": config_hash,
                "external_signal_hash": external_signal_hash,
                "price_snapshot_hash": price_snapshot_hash,
                "evidence_hashes": [evidence_hash],
            }
        )
        signal = merge_mgfs_agent_signals(
            symbol=symbol,
            name=name,
            as_of_date=end_date,
            signals=[
                MGFSAgentSignal(
                    source="static_score_agent",
                    action=action,
                    score=normalized_score,
                    confidence=0.6,
                    rationale=f"{name} 静态 MGFS 分数 {static_score:.1f} 用作历史回测前研究快照。",
                    evidence_hashes=[evidence_hash],
                )
            ],
            weights={"static_score_agent": 1.0},
            config_hash=config_hash,
            price_snapshot_hash=price_snapshot_hash,
        )
        signal_lines.append(signal.to_json())
        discussion_lines.append(
            f"- {name}({symbol}): 静态分 {static_score:.1f}, "
            f"price_snapshot_hash={price_snapshot_hash}, "
            f"external_signal_hash={external_signal_hash}, "
            f"evidence_hash={evidence_hash}\n"
        )

    (output_dir / "decision_inputs.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in decisions) + ("\n" if decisions else ""),
        encoding="utf-8",
    )
    (output_dir / "mgfs_research_signal_v1.jsonl").write_text(
        "\n".join(signal_lines) + ("\n" if signal_lines else ""),
        encoding="utf-8",
    )
    (output_dir / "agent_discussion.md").write_text("".join(discussion_lines), encoding="utf-8")
    summary = {
        "ok": bool(decisions),
        "run_id": f"MGFS_BACKTEST_{start_date.isoformat()}_{end_date.isoformat()}",
        "decision_count": len(decisions),
        "symbol_count": len(active_symbols),
        "adapter_status": {
            "point_in_time_inputs": "enabled",
            "research_signal_schema": "mgfs_research_signal_v1",
            "instruction_boundary": "research_only",
            "external_signal_hash_binding": "enabled",
        },
        "borrowed_from": {
            "repo": "utopia",
            "patterns": [
                "point_in_time_inputs",
                "alpha_signal_jsonl",
                "run_artifact_validation",
            ],
        },
    }
    (output_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report = validate_mgfs_research_run(output_dir, expected_symbols=active_symbols)
    (output_dir / "run_validation_report.json").write_text(report.to_json() + "\n", encoding="utf-8")
    return report

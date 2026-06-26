from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sentinel.mgfs.evolution.research_signal import (
    MGFSAgentSignal,
    MGFSDecisionInput,
    MGFSEvidenceEvent,
    MGFSResearchSignalExpiredError,
    MGFSResearchSignalV1,
    PointInTimeViolation,
    load_latest_research_signal,
    merge_mgfs_agent_signals,
)


def _event(
    *,
    content_hash: str = "event-hash",
    available_at: date = date(2026, 6, 20),
) -> MGFSEvidenceEvent:
    return MGFSEvidenceEvent(
        source="external_policy_snapshot",
        title="机器人政策更新",
        detail="政策信号在决策日之前已经可见。",
        published_at=date(2026, 6, 19),
        collected_at=date(2026, 6, 20),
        available_at=available_at,
        content_hash=content_hash,
    )


def test_decision_input_rejects_evidence_not_available_at_as_of_date():
    with pytest.raises(PointInTimeViolation, match="available_at"):
        MGFSDecisionInput(
            symbol="300750",
            name="宁德时代",
            as_of_date=date(2026, 6, 20),
            score_snapshot={"moat": 88.0, "valuation": 62.0},
            config_hash="config-hash",
            price_snapshot_hash="price-hash",
            events=[_event(available_at=date(2026, 6, 21))],
        )


def test_merge_mgfs_agent_signals_preserves_evidence_scores_and_boundary():
    signal = merge_mgfs_agent_signals(
        symbol="300750",
        name="宁德时代",
        as_of_date=date(2026, 6, 20),
        signals=[
            MGFSAgentSignal(
                source="moat_agent",
                action="increase_attention",
                score=0.6,
                confidence=0.8,
                rationale="护城河证据仍然支持核心池观察。",
                evidence_hashes=["moat-hash", "shared-hash"],
            ),
            MGFSAgentSignal(
                source="risk_agent",
                action="reduce_attention",
                score=-0.2,
                confidence=0.6,
                rationale="估值和事件证据需要反向复核。",
                evidence_hashes=["risk-hash", "shared-hash"],
                risk_flags=["valuation_gap"],
            ),
        ],
        weights={"moat_agent": 0.7, "risk_agent": 0.3},
        config_hash="config-hash",
        price_snapshot_hash="price-hash",
    )

    assert signal.schema_version == "mgfs_research_signal_v1"
    assert signal.action_hint == "increase_attention"
    assert signal.instruction_boundary == "research_only"
    assert signal.score == pytest.approx(0.36)
    assert signal.source_scores == {"moat_agent": 0.6, "risk_agent": -0.2}
    assert signal.evidence_hashes == ["moat-hash", "risk-hash", "shared-hash"]
    assert signal.risk_flags == ["conflict", "valuation_gap"]
    assert signal.config_hash == "config-hash"
    assert signal.price_snapshot_hash == "price-hash"
    assert MGFSResearchSignalV1.from_json(signal.to_json()) == signal


def test_load_latest_research_signal_ignores_future_signals(tmp_path: Path):
    signal_path = tmp_path / "mgfs_research_signal_v1.jsonl"
    visible = MGFSResearchSignalV1(
        symbol="300750",
        name="宁德时代",
        as_of_date="2026-06-20",
        action_hint="increase_attention",
        score=0.42,
        confidence=0.7,
        rationale="可见历史信号。",
        evidence_hashes=["visible-hash"],
        source_scores={"moat_agent": 0.42},
        risk_flags=[],
        config_hash="config-visible",
        price_snapshot_hash="price-visible",
        expires_at="2026-06-23",
    )
    future = MGFSResearchSignalV1(
        symbol="300750",
        name="宁德时代",
        as_of_date="2026-06-24",
        action_hint="reduce_attention",
        score=-0.5,
        confidence=0.8,
        rationale="未来信号不应该被读取。",
        evidence_hashes=["future-hash"],
        source_scores={"risk_agent": -0.5},
        risk_flags=[],
        config_hash="config-future",
        price_snapshot_hash="price-future",
        expires_at="2026-06-27",
    )
    signal_path.write_text(visible.to_json() + "\n" + future.to_json() + "\n", encoding="utf-8")

    loaded = load_latest_research_signal(
        signal_path,
        symbol="300750",
        as_of_date=date(2026, 6, 22),
    )

    assert loaded == visible


def test_load_latest_research_signal_treats_expiry_as_exclusive(tmp_path: Path):
    signal_path = tmp_path / "mgfs_research_signal_v1.jsonl"
    expired = MGFSResearchSignalV1(
        symbol="300750",
        name="宁德时代",
        as_of_date="2026-06-20",
        action_hint="increase_attention",
        score=0.42,
        confidence=0.7,
        rationale="边界日已过期。",
        evidence_hashes=["visible-hash"],
        source_scores={"moat_agent": 0.42},
        risk_flags=[],
        config_hash="config-visible",
        price_snapshot_hash="price-visible",
        expires_at="2026-06-23",
    )
    signal_path.write_text(expired.to_json() + "\n", encoding="utf-8")

    with pytest.raises(MGFSResearchSignalExpiredError):
        load_latest_research_signal(
            signal_path,
            symbol="300750",
            as_of_date=date(2026, 6, 23),
        )

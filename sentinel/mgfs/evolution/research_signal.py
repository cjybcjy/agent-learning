from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any, Literal, Mapping


ActionHint = Literal["increase_attention", "reduce_attention", "hold_review"]


class PointInTimeViolation(ValueError):
    """Raised when a decision input includes evidence not visible on that date."""


class MGFSResearchSignalNotFoundError(FileNotFoundError):
    """Raised when no research signal exists for a symbol/date."""


class MGFSResearchSignalExpiredError(ValueError):
    """Raised when a visible research signal is stale for the requested date."""


def _coerce_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


@dataclass(frozen=True, slots=True)
class MGFSEvidenceEvent:
    source: str
    title: str
    detail: str
    published_at: str | date
    collected_at: str | date
    available_at: str | date
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "published_at", _coerce_date(self.published_at))
        object.__setattr__(self, "collected_at", _coerce_date(self.collected_at))
        object.__setattr__(self, "available_at", _coerce_date(self.available_at))


@dataclass(frozen=True, slots=True)
class MGFSDecisionInput:
    symbol: str
    name: str
    as_of_date: str | date
    score_snapshot: Mapping[str, float]
    config_hash: str
    price_snapshot_hash: str
    events: list[MGFSEvidenceEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        normalized_as_of_date = _coerce_date(self.as_of_date)
        object.__setattr__(self, "as_of_date", normalized_as_of_date)
        for event in self.events:
            if _coerce_date(event.available_at) > normalized_as_of_date:
                raise PointInTimeViolation(
                    f"event {event.content_hash} has available_at "
                    f"{event.available_at.isoformat()} after as_of_date "
                    f"{normalized_as_of_date.isoformat()}"
                )

    @property
    def evidence_hashes(self) -> list[str]:
        return sorted({event.content_hash for event in self.events if event.content_hash})


@dataclass(frozen=True, slots=True)
class MGFSAgentSignal:
    source: str
    action: ActionHint
    score: float
    confidence: float
    rationale: str = ""
    evidence_hashes: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    hard_risk: bool = False


@dataclass(frozen=True, slots=True)
class MGFSResearchSignalV1:
    symbol: str
    name: str
    as_of_date: str
    action_hint: ActionHint
    score: float
    confidence: float
    rationale: str
    evidence_hashes: list[str]
    source_scores: dict[str, float]
    risk_flags: list[str]
    config_hash: str
    price_snapshot_hash: str
    expires_at: str
    instruction_boundary: str = "research_only"
    schema_version: str = "mgfs_research_signal_v1"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "MGFSResearchSignalV1":
        data = json.loads(payload)
        if data.get("schema_version") != "mgfs_research_signal_v1":
            raise ValueError("unsupported MGFS research signal schema")
        return cls(**data)


def merge_mgfs_agent_signals(
    *,
    symbol: str,
    name: str,
    as_of_date: str | date,
    signals: list[MGFSAgentSignal],
    config_hash: str,
    price_snapshot_hash: str,
    weights: dict[str, float] | None = None,
    min_abs_score: float = 0.2,
    conflict_min_abs_score: float = 0.2,
    ttl_days: int = 3,
) -> MGFSResearchSignalV1:
    if not signals:
        raise ValueError("at least one MGFS agent signal is required")
    if ttl_days < 1:
        raise ValueError("ttl_days must be >= 1")

    active_weights = weights or {signal.source: 1.0 / len(signals) for signal in signals}
    weighted_score = sum(float(signal.score) * active_weights.get(signal.source, 0.0) for signal in signals)
    confidence = sum(max(0.0, min(1.0, float(signal.confidence))) for signal in signals) / len(signals)
    evidence_hashes = sorted({item for signal in signals for item in signal.evidence_hashes if item})
    risk_flags = sorted({item for signal in signals for item in signal.risk_flags if item})
    has_positive = any(signal.score >= conflict_min_abs_score for signal in signals)
    has_negative = any(signal.score <= -conflict_min_abs_score for signal in signals)
    hard_risk = any(signal.hard_risk for signal in signals)

    if has_positive and has_negative:
        risk_flags = sorted(set(risk_flags + ["conflict"]))
    if hard_risk:
        action_hint: ActionHint = "hold_review"
        risk_flags = sorted(set(risk_flags + ["hard_risk"]))
    elif weighted_score >= min_abs_score:
        action_hint = "increase_attention"
    elif weighted_score <= -min_abs_score:
        action_hint = "reduce_attention"
    else:
        action_hint = "hold_review"
        risk_flags = sorted(set(risk_flags + ["weak_signal"]))

    normalized_as_of_date = _coerce_date(as_of_date)
    expires_at = normalized_as_of_date + timedelta(days=ttl_days)
    rationale = " | ".join(signal.rationale for signal in signals if signal.rationale)

    return MGFSResearchSignalV1(
        symbol=symbol,
        name=name,
        as_of_date=normalized_as_of_date.isoformat(),
        action_hint=action_hint,
        score=round(weighted_score, 10),
        confidence=round(confidence, 10),
        rationale=rationale,
        evidence_hashes=evidence_hashes,
        source_scores={signal.source: float(signal.score) for signal in signals},
        risk_flags=risk_flags,
        config_hash=config_hash,
        price_snapshot_hash=price_snapshot_hash,
        expires_at=expires_at.isoformat(),
    )


def load_latest_research_signal(
    path: str | Path,
    *,
    symbol: str,
    as_of_date: str | date,
) -> MGFSResearchSignalV1:
    signal_path = Path(path)
    normalized_as_of_date = _coerce_date(as_of_date)
    latest: MGFSResearchSignalV1 | None = None
    latest_as_of_date: date | None = None

    for line in signal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        signal = MGFSResearchSignalV1.from_json(line)
        signal_date = _coerce_date(signal.as_of_date)
        if signal.symbol != symbol or signal_date > normalized_as_of_date:
            continue
        if latest_as_of_date is not None and signal_date < latest_as_of_date:
            continue
        latest = signal
        latest_as_of_date = signal_date

    if latest is None:
        raise MGFSResearchSignalNotFoundError(f"no MGFS research signal found for {symbol}")
    if _coerce_date(latest.expires_at) <= normalized_as_of_date:
        raise MGFSResearchSignalExpiredError(
            f"MGFS research signal for {symbol} expired at {latest.expires_at}"
        )
    return latest

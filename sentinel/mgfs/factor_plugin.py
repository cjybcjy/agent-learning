from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from strenum import StrEnum
from typing import Any

from sentinel.domain.models import Market


@dataclass(frozen=True, slots=True)
class TargetInfo:
    symbol: str
    market: Market
    asset_class: str
    name: str | None = None
    sector: str | None = None
    tags: list[str] = field(default_factory=list)


class AlertLevel(StrEnum):
    HARD_VETO = "hard_veto"
    SOFT_VETO = "soft_veto"
    YELLOW_WARNING = "yellow_warning"
    GREEN_PASS = "green_pass"


@dataclass(slots=True)
class FactorScore:
    factor_key: str
    factor_name: str
    score: float
    max_score: float = 100.0
    weight: float = 0.0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
    is_veto: bool = False
    veto_reason: str | None = None

    @property
    def normalized_score(self) -> float:
        if self.max_score <= 0:
            return 0.0
        return self.score / self.max_score


class BaseFactorPlugin(ABC):
    factor_key: str
    factor_name: str
    default_weight: float = 0.0

    @abstractmethod
    def evaluate(self, target: TargetInfo) -> FactorScore:
        raise NotImplementedError

    def is_applicable(self, target: TargetInfo) -> bool:
        """Return True if this plugin should evaluate the given target.

        Subclasses may override to declare asset-class or market-specific
        applicability. Non-applicable plugins are skipped entirely by the
        orchestrator (no weight assigned, no fallback score generated).
        """
        return True

    def health_check(self) -> dict[str, Any]:
        return {"ready": True, "missing_dependencies": []}

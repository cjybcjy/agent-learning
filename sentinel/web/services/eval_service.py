from __future__ import annotations

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.orchestrator import InvestmentDecision
from sentinel.web.dependencies import get_orchestrator


def evaluate_single(
    symbol: str,
    market: str,
    asset_class: str = "equity",
    sector: str | None = None,
    policy_rating: str = "neutral",
) -> InvestmentDecision:
    orchestrator = get_orchestrator()
    target = TargetInfo(
        symbol=symbol,
        market=Market[market],
        asset_class=asset_class,
        sector=sector,
    )
    return orchestrator.evaluate(target, policy_rating=policy_rating)

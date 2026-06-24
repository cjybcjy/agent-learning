from __future__ import annotations

from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.mgfs.orchestrator import InvestmentDecision
from sentinel.mgfs.target_resolver import TargetResolver
from sentinel.web.dependencies import get_orchestrator


def evaluate_single(
    symbol: str,
    market: str,
    asset_class: str = "equity",
    sector: str | None = None,
    policy_rating: str = "neutral",
    target_resolver: TargetResolver | None = None,
) -> InvestmentDecision:
    orchestrator = get_orchestrator()
    market_enum = Market[market]
    if target_resolver is None:
        settings = AppSettings()
        target_resolver = TargetResolver(settings.resolved_config_dir / "moat_static_base.yaml")
    target = target_resolver.resolve(
        symbol=symbol,
        market=market_enum,
        asset_class=asset_class,
        sector=sector,
    )
    return orchestrator.evaluate(target, policy_rating=policy_rating)

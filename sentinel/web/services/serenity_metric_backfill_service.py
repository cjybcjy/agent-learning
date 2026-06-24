from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.storage.db import Database
from sentinel.web.services.serenity_verification_service import _default_metric_targets


@dataclass(frozen=True, slots=True)
class SerenityMetricBackfillResult:
    symbol: str
    market: str
    inserted_count: int
    trend_count: int
    safety_count: int
    metric_names: list[str]
    recorded_at: datetime


class SerenityMetricBackfillService:
    """Persist user-verified Serenity metric scores with source traceability."""

    def __init__(self, database_path: Path | None = None) -> None:
        settings = AppSettings()
        self.database_path = database_path or settings.database_path

    def backfill(
        self,
        *,
        symbol: str,
        market: str,
        values: dict[str, float],
        source: str,
        as_of: date,
        source_url: str | None = None,
        recorded_at: datetime | None = None,
    ) -> SerenityMetricBackfillResult:
        clean_source = source.strip()
        if not clean_source:
            raise ValueError("source is required")
        if recorded_at is None:
            recorded_at = datetime.now(tz=timezone.utc)

        market_enum = _parse_market(market)
        target = TargetInfo(
            symbol=symbol.strip(),
            market=market_enum,
            asset_class="equity",
        )
        metric_targets = {item.metric_name: item for item in _default_metric_targets()}
        agg = MetricsAggregator(Database(self.database_path))
        agg.bootstrap()

        trend_count = 0
        safety_count = 0
        metric_names: list[str] = []
        for metric_name, raw_value in values.items():
            metric_target = metric_targets.get(metric_name)
            if metric_target is None:
                raise ValueError(f"unsupported metric: {metric_name}")
            value = _validate_score_value(metric_name, raw_value)

            if metric_target.target_table == "trend_metrics":
                agg.insert_trend_metric(target, metric_name, value, recorded_at)
                trend_count += 1
            elif metric_target.target_table == "safety_metrics":
                agg.insert_safety_metric(target, metric_name, value, recorded_at)
                safety_count += 1
            else:
                raise ValueError(
                    f"unsupported metric table: {metric_target.target_table}"
                )

            agg.record_metric_source(
                target,
                metric_name=metric_name,
                target_table=metric_target.target_table,
                source=clean_source,
                as_of=as_of,
                source_url=source_url.strip() if source_url else None,
                financial_items=metric_target.financial_items,
                calculation_hint=metric_target.calculation_hint,
                recorded_at=recorded_at,
            )
            metric_names.append(metric_name)

        if not metric_names:
            raise ValueError("at least one metric value is required")

        return SerenityMetricBackfillResult(
            symbol=target.symbol,
            market=market,
            inserted_count=len(metric_names),
            trend_count=trend_count,
            safety_count=safety_count,
            metric_names=metric_names,
            recorded_at=recorded_at,
        )


def _parse_market(market: str) -> Market:
    normalized = market.strip()
    if normalized in Market.__members__:
        return Market[normalized]
    return Market(normalized)


def _validate_score_value(metric_name: str, value: float) -> float:
    score = float(value)
    if not math.isfinite(score):
        raise ValueError(f"{metric_name} must be finite")
    if score < 0.0 or score > 100.0:
        raise ValueError(f"{metric_name} must be between 0 and 100")
    return score

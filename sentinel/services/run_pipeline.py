from __future__ import annotations

from datetime import datetime, timezone

from sentinel.domain.models import HeatSnapshot, Market
from sentinel.storage.repository import HeatMetricRepository


class RunPipelineService:
    def __init__(self, repository: HeatMetricRepository) -> None:
        self.repository = repository

    def run_market(self, market: Market) -> list[HeatSnapshot]:
        snapshot = HeatSnapshot(
            timestamp=datetime.now(tz=timezone.utc).replace(tzinfo=None),
            market=market,
            symbol=f"SYNTH-{market.value}",
            base_heat=10.0,
            kol_multiplier=1.0,
            sentiment_score=0.25,
            directed_heat=2.5,
            change_pct=None,
            top_source="synthetic",
            rank_bullish=1,
            rank_bearish=None,
            is_anomaly=False,
        )
        self.repository.upsert_snapshots([snapshot])
        return [snapshot]

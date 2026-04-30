from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sentinel.analyzers import WeightsConfig
from sentinel.analyzers.sentiment import NullSentimentAnalyzer, SentimentAnalyzer
from sentinel.collectors.registry import CollectorRegistry
from sentinel.collectors.synthetic import build_default_registry
from sentinel.config import AppSettings, get_market_collectors, load_market_config, load_weights_config
from sentinel.domain.models import HeatSnapshot, Market
from sentinel.services.run_pipeline import RunPipelineService
from sentinel.storage.db import Database
from sentinel.storage.repository import HeatMetricRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SentinelApplication:
    repository: HeatMetricRepository
    runner: RunPipelineService
    market_config: dict[str, dict[str, object]]

    def run_market(self, market: Market, collector_keys: list[str] | None = None) -> list[HeatSnapshot]:
        self.repository.bootstrap()
        keys = collector_keys or get_market_collectors(self.market_config, market.value)
        previous_heats = self.repository.get_previous_heats(market)
        snapshots = self.runner.run_market(market=market, collector_keys=keys, previous_heats=previous_heats)
        self.repository.upsert_snapshots(snapshots)
        return snapshots


def build_application(settings: AppSettings) -> SentinelApplication:
    database = Database(settings.database_path)
    repository = HeatMetricRepository(database)
    registry = build_default_registry()
    weights_raw = load_weights_config(settings.resolved_config_dir / "weights.yaml")
    base_heat = weights_raw.get("base_heat", {})
    weights = WeightsConfig(
        posts=float(base_heat.get("posts", 0.35)),
        comments=float(base_heat.get("comments", 0.30)),
        likes=float(base_heat.get("likes", 0.20)),
        shares=float(base_heat.get("shares", 0.15)),
        kol_multiplier=float(weights_raw.get("kol_multiplier", 3.0)),
    )

    # Load sentiment model if configured
    model_dir = settings.resolved_config_dir.parent / "models" / "finbert_en"
    if model_dir.exists() and (model_dir / "model.onnx").exists():
        logger.info("Loading FinBERT model from %s", model_dir)
        sentiment_analyzer: SentimentAnalyzer | NullSentimentAnalyzer = SentimentAnalyzer(model_dir)
    else:
        logger.info("No FinBERT model found, using neutral sentiment")
        sentiment_analyzer = NullSentimentAnalyzer()

    runner = RunPipelineService(registry, weights, sentiment_analyzer)
    market_config = load_market_config(settings.resolved_config_dir / "markets.yaml")
    return SentinelApplication(repository=repository, runner=runner, market_config=market_config)

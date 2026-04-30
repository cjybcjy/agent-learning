from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from sentinel.analyzers import WeightsConfig, compute_heat
from sentinel.analyzers.ranking import rank_snapshots
from sentinel.analyzers.sentiment import NullSentimentAnalyzer, SentimentAnalyzer
from sentinel.antispam import filter_spam
from sentinel.collectors.base import RawMention
from sentinel.collectors.registry import CollectorRegistry
from sentinel.domain.models import HeatSnapshot, Market

logger = logging.getLogger(__name__)


class RunPipelineService:
    def __init__(
        self,
        registry: CollectorRegistry,
        weights: WeightsConfig | None = None,
        sentiment_analyzer: SentimentAnalyzer | NullSentimentAnalyzer | None = None,
    ) -> None:
        self.registry = registry
        self.weights = weights or WeightsConfig()
        self.sentiment = sentiment_analyzer or NullSentimentAnalyzer()

    def run_market(self, market: Market, collector_keys: list[str], previous_heats: dict[str, float] | None = None) -> list[HeatSnapshot]:
        timestamp = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        raw = asyncio.run(self._collect_market(market, collector_keys, timestamp))
        clean = filter_spam(raw)

        # Compute per-symbol sentiment scores
        sentiment_scores = self._compute_sentiment(clean)

        snapshots = compute_heat(clean, self.weights, timestamp, sentiment_scores=sentiment_scores)

        # Compute Δ% from previous period
        if previous_heats:
            for s in snapshots:
                prev = previous_heats.get(s.symbol)
                if prev is not None and abs(prev) > 1e-9:
                    s.change_pct = round((abs(s.directed_heat) - abs(prev)) / abs(prev) * 100, 2)

        ranked = rank_snapshots(snapshots, top_n=10)
        return ranked

    def _compute_sentiment(self, mentions: list[RawMention]) -> dict[str, float]:
        """Aggregate texts per symbol, score with FinBERT, average per symbol."""
        if not mentions:
            return {}

        # Group raw_text by symbol
        symbol_texts: dict[str, list[str]] = defaultdict(list)
        for m in mentions:
            if m.raw_text.strip():
                symbol_texts[m.symbol].append(m.raw_text)

        # Flatten all texts for batch scoring
        all_texts: list[str] = []
        text_to_symbol: list[str] = []
        for symbol, texts in symbol_texts.items():
            for t in texts:
                all_texts.append(t)
                text_to_symbol.append(symbol)

        if not all_texts:
            return {}

        scores = self.sentiment.score_texts(all_texts)

        # Average scores per symbol
        symbol_score_sums: dict[str, float] = defaultdict(float)
        symbol_score_counts: dict[str, int] = defaultdict(int)
        for symbol, score in zip(text_to_symbol, scores):
            symbol_score_sums[symbol] += score
            symbol_score_counts[symbol] += 1

        return {
            symbol: round(symbol_score_sums[symbol] / symbol_score_counts[symbol], 4)
            for symbol in symbol_score_sums
        }

    async def _collect_market(self, market: Market, collector_keys: list[str], timestamp: datetime) -> list[RawMention]:
        collectors = self.registry.list_for_market(market, collector_keys)
        batches = await asyncio.gather(*(collector.collect(timestamp) for collector in collectors))
        return [mention for batch in batches for mention in batch]

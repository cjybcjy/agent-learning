"""Tests for sentiment analyzer — uses NullSentimentAnalyzer and mocks."""
from datetime import datetime
from unittest.mock import patch

from sentinel.analyzers.sentiment import NullSentimentAnalyzer, SentimentAnalyzer
from sentinel.collectors.base import RawMention, StaticCollector
from sentinel.collectors.registry import CollectorRegistry
from sentinel.domain.models import Market
from sentinel.services.run_pipeline import RunPipelineService


def test_null_analyzer_returns_zeros() -> None:
    analyzer = NullSentimentAnalyzer()
    scores = analyzer.score_texts(["bullish", "bearish", "neutral"])
    assert scores == [0.0, 0.0, 0.0]


def test_null_analyzer_empty_input() -> None:
    analyzer = NullSentimentAnalyzer()
    assert analyzer.score_texts([]) == []


def test_sentiment_analyzer_fallback_on_missing_model(tmp_path) -> None:
    """When model file doesn't exist, score_texts returns neutral."""
    analyzer = SentimentAnalyzer(model_dir=tmp_path / "nonexistent")
    scores = analyzer.score_texts(["some text"])
    assert scores == [0.0]


def test_pipeline_uses_sentiment_scores() -> None:
    """Pipeline computes per-symbol sentiment and feeds to heat calculator."""
    registry = CollectorRegistry()
    registry.register(
        StaticCollector(
            market=Market.A_SHARE,
            platform="synthetic",
            mentions=[
                RawMention(
                    market=Market.A_SHARE,
                    platform="synthetic",
                    symbol="600519",
                    post_count=5,
                    comment_count=10,
                    like_count=20,
                    share_count=3,
                    raw_text="贵州茅台强势上涨",
                    is_kol=False,
                    account_age_days=365,
                    account_followers=100,
                    source_url="https://example.test/1",
                    post_time=datetime(2026, 4, 29, 10, 0, 0),
                ),
            ],
        )
    )

    # Mock sentiment to return a known score
    class MockSentiment:
        def score_texts(self, texts: list[str]) -> list[float]:
            return [0.8] * len(texts)

    runner = RunPipelineService(registry=registry, sentiment_analyzer=MockSentiment())
    snapshots = runner.run_market(market=Market.A_SHARE, collector_keys=["synthetic"])

    assert len(snapshots) == 1
    s = snapshots[0]
    assert s.sentiment_score == 0.8
    # directed_heat = V_base * M_kol * Sent = 1.0 * 1.0 * 0.8 = 0.8
    assert s.directed_heat == 0.8


def test_pipeline_bearish_sentiment() -> None:
    """Negative sentiment produces negative directed_heat."""
    registry = CollectorRegistry()
    registry.register(
        StaticCollector(
            market=Market.US,
            platform="synthetic",
            mentions=[
                RawMention(
                    market=Market.US,
                    platform="synthetic",
                    symbol="NVDA",
                    post_count=5,
                    comment_count=10,
                    like_count=20,
                    share_count=3,
                    raw_text="NVDA crashing hard sell-off",
                    is_kol=False,
                    account_age_days=365,
                    account_followers=100,
                    source_url="https://example.test/2",
                    post_time=datetime(2026, 4, 29, 10, 0, 0),
                ),
            ],
        )
    )

    class BearishSentiment:
        def score_texts(self, texts: list[str]) -> list[float]:
            return [-0.7] * len(texts)

    runner = RunPipelineService(registry=registry, sentiment_analyzer=BearishSentiment())
    snapshots = runner.run_market(market=Market.US, collector_keys=["synthetic"])

    assert len(snapshots) == 1
    assert snapshots[0].directed_heat < 0
    assert snapshots[0].sentiment_score == -0.7

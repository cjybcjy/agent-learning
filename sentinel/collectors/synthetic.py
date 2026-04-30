from __future__ import annotations

from datetime import datetime

from sentinel.collectors.base import RawMention, StaticCollector
from sentinel.collectors.registry import CollectorRegistry
from sentinel.domain.models import Market


def build_default_registry() -> CollectorRegistry:
    registry = CollectorRegistry()
    now = datetime(2026, 4, 29, 10, 0, 0)
    registry.register(
        StaticCollector(
            market=Market.A_SHARE,
            platform="synthetic",
            mentions=[
                RawMention(
                    market=Market.A_SHARE,
                    platform="synthetic",
                    symbol="SYNTH-A股",
                    post_count=1,
                    comment_count=2,
                    like_count=3,
                    share_count=0,
                    raw_text="Synthetic A-share mention",
                    is_kol=False,
                    account_age_days=365,
                    account_followers=10,
                    source_url="https://example.test/a-share",
                    post_time=now,
                )
            ],
        )
    )
    registry.register(
        StaticCollector(
            market=Market.US,
            platform="synthetic",
            mentions=[
                RawMention(
                    market=Market.US,
                    platform="synthetic",
                    symbol="SYNTH-US",
                    post_count=1,
                    comment_count=2,
                    like_count=3,
                    share_count=0,
                    raw_text="Synthetic US mention",
                    is_kol=False,
                    account_age_days=365,
                    account_followers=10,
                    source_url="https://example.test/us",
                    post_time=now,
                )
            ],
        )
    )
    registry.register(
        StaticCollector(
            market=Market.CRYPTO,
            platform="synthetic",
            mentions=[
                RawMention(
                    market=Market.CRYPTO,
                    platform="synthetic",
                    symbol="SYNTH-CRYPTO",
                    post_count=1,
                    comment_count=2,
                    like_count=3,
                    share_count=0,
                    raw_text="Synthetic crypto mention",
                    is_kol=False,
                    account_age_days=365,
                    account_followers=10,
                    source_url="https://example.test/crypto",
                    post_time=now,
                )
            ],
        )
    )
    return registry

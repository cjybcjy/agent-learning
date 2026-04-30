from datetime import datetime

from sentinel.collectors.base import RawMention, StaticCollector
from sentinel.domain.models import Market


def test_raw_mention_to_dict_contains_market_and_platform() -> None:
    mention = RawMention(
        market=Market.A_SHARE,
        platform="xueqiu",
        symbol="600519",
        post_count=4,
        comment_count=10,
        like_count=20,
        share_count=3,
        raw_text="贵州茅台放量上涨",
        is_kol=False,
        account_age_days=365,
        account_followers=120,
        source_url="https://example.test/post/1",
        post_time=datetime(2026, 4, 29, 10, 0, 0),
    )

    payload = mention.to_dict()

    assert payload["market"] == "A股"
    assert payload["platform"] == "xueqiu"
    assert payload["symbol"] == "600519"


def test_static_collector_exposes_platform_and_market() -> None:
    collector = StaticCollector(market=Market.A_SHARE, platform="synthetic", mentions=[])

    assert collector.market is Market.A_SHARE
    assert collector.platform == "synthetic"

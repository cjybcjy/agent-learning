from datetime import datetime

from sentinel.antispam import filter_spam
from sentinel.collectors.base import RawMention
from sentinel.domain.models import Market


def _mention(account_age_days: int = 365, account_followers: int = 100, symbol: str = "600519", source_url: str = "https://example.test/1") -> RawMention:
    return RawMention(
        market=Market.A_SHARE,
        platform="xueqiu",
        symbol=symbol,
        post_count=1,
        comment_count=5,
        like_count=10,
        share_count=2,
        raw_text="test",
        is_kol=False,
        account_age_days=account_age_days,
        account_followers=account_followers,
        source_url=source_url,
        post_time=datetime(2026, 4, 29, 10, 0, 0),
    )


def test_filter_removes_young_accounts() -> None:
    mentions = [_mention(account_age_days=10)]
    assert filter_spam(mentions) == []


def test_filter_removes_low_follower_accounts() -> None:
    mentions = [_mention(account_followers=5)]
    assert filter_spam(mentions) == []


def test_filter_deduplicates_same_url_same_symbol() -> None:
    mentions = [
        _mention(source_url="https://example.test/dup"),
        _mention(source_url="https://example.test/dup"),
    ]
    result = filter_spam(mentions)
    assert len(result) == 1


def test_filter_keeps_valid_mentions() -> None:
    mentions = [
        _mention(source_url="https://example.test/a"),
        _mention(source_url="https://example.test/b", symbol="000001"),
    ]
    result = filter_spam(mentions)
    assert len(result) == 2

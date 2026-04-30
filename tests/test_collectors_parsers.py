from datetime import datetime

from sentinel.collectors.coingecko import parse_coingecko_payload
from sentinel.collectors.reddit_stocks import parse_reddit_listing
from sentinel.collectors.xueqiu import parse_xueqiu_timeline
from sentinel.domain.models import Market


def test_parse_xueqiu_timeline_builds_raw_mentions() -> None:
    payload = {
        "list": [
            {
                "title": "茅台走强",
                "description": "600519 再次走高",
                "comment_count": 12,
                "like_count": 30,
                "retweet_count": 2,
                "created_at": 1777437600000,
                "user": {"followers_count": 80, "created_at": 1640995200000},
                "target": "600519",
                "uri": "/S/SH600519",
            }
        ]
    }

    mentions = parse_xueqiu_timeline(payload, datetime(2026, 4, 29, 10, 0, 0))

    assert len(mentions) == 1
    assert mentions[0].market is Market.A_SHARE
    assert mentions[0].platform == "xueqiu"
    assert mentions[0].symbol == "600519"


def test_parse_reddit_listing_builds_raw_mentions() -> None:
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "NVDA is breaking out",
                        "selftext": "Bullish setup into earnings",
                        "num_comments": 88,
                        "score": 640,
                        "created_utc": 1777437600,
                        "author_created_utc": 1609459200,
                        "subreddit": "stocks",
                        "permalink": "/r/stocks/comments/demo",
                    }
                }
            ]
        }
    }

    mentions = parse_reddit_listing(payload, datetime(2026, 4, 29, 10, 0, 0), symbol="NVDA")

    assert len(mentions) == 1
    assert mentions[0].market is Market.US
    assert mentions[0].symbol == "NVDA"


def test_parse_coingecko_payload_builds_raw_mentions() -> None:
    payload = {
        "coins": [
            {
                "symbol": "btc",
                "name": "Bitcoin",
                "sentiment_votes_up_percentage": 82.3,
                "watchlist_portfolio_users": 250000,
            }
        ]
    }

    mentions = parse_coingecko_payload(payload, datetime(2026, 4, 29, 10, 0, 0))

    assert len(mentions) == 1
    assert mentions[0].market is Market.CRYPTO
    assert mentions[0].platform == "coingecko"
    assert mentions[0].symbol == "BTC"

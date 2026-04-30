from datetime import datetime

from sentinel.analyzers import WeightsConfig, compute_heat
from sentinel.collectors.base import RawMention
from sentinel.domain.models import Market


def _mention(symbol: str = "600519", is_kol: bool = False, platform: str = "xueqiu") -> RawMention:
    return RawMention(
        market=Market.A_SHARE,
        platform=platform,
        symbol=symbol,
        post_count=10,
        comment_count=20,
        like_count=30,
        share_count=5,
        raw_text="test",
        is_kol=is_kol,
        account_age_days=365,
        account_followers=100,
        source_url=f"https://example.test/{symbol}",
        post_time=datetime(2026, 4, 29, 10, 0, 0),
    )


def test_compute_heat_single_symbol_no_sentiment() -> None:
    mentions = [_mention()]
    weights = WeightsConfig()
    ts = datetime(2026, 4, 29, 10, 0, 0)

    snapshots = compute_heat(mentions, weights, ts, sentiment_score=0.0)

    assert len(snapshots) == 1
    s = snapshots[0]
    assert s.symbol == "600519"
    # single symbol: all norms = 1.0, V_base = 0.35+0.30+0.20+0.15 = 1.0
    assert s.base_heat == 1.0
    # no KOL: M_kol = 1.0
    assert s.kol_multiplier == 1.0
    # sentiment=0.0 → directed_heat = V_base * M_kol (neutral mode)
    assert s.directed_heat == 1.0


def test_compute_heat_kol_amplifies() -> None:
    mentions = [_mention(is_kol=True)]
    weights = WeightsConfig(kol_multiplier=3.0)
    ts = datetime(2026, 4, 29, 10, 0, 0)

    snapshots = compute_heat(mentions, weights, ts)

    # 1 mention, 1 is KOL: kol_ratio = 1.0, M_kol = 1 + 3*1 = 4.0
    assert snapshots[0].kol_multiplier == 4.0
    assert snapshots[0].directed_heat == 4.0


def test_compute_heat_with_sentiment_direction() -> None:
    mentions = [_mention()]
    weights = WeightsConfig()
    ts = datetime(2026, 4, 29, 10, 0, 0)

    snapshots = compute_heat(mentions, weights, ts, sentiment_score=-0.5)

    # V_base=1.0, M_kol=1.0, Sent=-0.5 → H = 1.0 * 1.0 * -0.5 = -0.5
    assert snapshots[0].directed_heat == -0.5
    assert snapshots[0].sentiment_score == -0.5


def test_compute_heat_multiple_symbols_normalization() -> None:
    m1 = RawMention(
        market=Market.A_SHARE, platform="xueqiu", symbol="600519",
        post_count=100, comment_count=200, like_count=300, share_count=50,
        raw_text="top", is_kol=False, account_age_days=365, account_followers=100,
        source_url="https://example.test/top", post_time=datetime(2026, 4, 29, 10, 0, 0),
    )
    m2 = RawMention(
        market=Market.A_SHARE, platform="xueqiu", symbol="000001",
        post_count=50, comment_count=100, like_count=150, share_count=25,
        raw_text="half", is_kol=False, account_age_days=365, account_followers=100,
        source_url="https://example.test/half", post_time=datetime(2026, 4, 29, 10, 0, 0),
    )
    weights = WeightsConfig()
    ts = datetime(2026, 4, 29, 10, 0, 0)

    snapshots = compute_heat([m1, m2], weights, ts)

    # m1 should have all norms = 1.0 → V_base = 1.0
    top = next(s for s in snapshots if s.symbol == "600519")
    half = next(s for s in snapshots if s.symbol == "000001")
    assert top.base_heat == 1.0
    # m2: all exactly half → norms = 0.5 → V_base = 0.5
    assert half.base_heat == 0.5


def test_compute_heat_empty_input() -> None:
    assert compute_heat([], WeightsConfig(), datetime(2026, 4, 29, 10, 0, 0)) == []

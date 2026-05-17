from sentinel.domain.models import Market
from sentinel.mgfs.data.price_fetcher import OHLCV, PriceFetcher
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.timing import TimingFactorPlugin


class _StaticBarsFetcher(PriceFetcher):
    """Return pre-defined OHLCV bars for testing."""

    def __init__(self, bars: list[OHLCV]) -> None:
        self._bars = bars

    def fetch_ohlcv(
        self, symbol: str, market: Market, days: int = 120
    ) -> list[OHLCV]:
        return self._bars


def _make_bars(n: int, close: float = 100.0, **overrides) -> list[OHLCV]:
    """Generate n identical OHLCV bars with optional per-field overrides."""
    bars: list[OHLCV] = []
    for i in range(n):
        bars.append(
            OHLCV(
                date=str(20240101 + i),
                open=overrides.get("open", close),
                high=overrides.get("high", close),
                low=overrides.get("low", close),
                close=close,
                volume=overrides.get("volume", 1_000_000),
            )
        )
    return bars


# ──────────────────────────────────────────────────────────────
# Test 1: Suspended trading / limit-up-down price freeze
# ──────────────────────────────────────────────────────────────

def test_suspended_trading_returns_neutral_score():
    """停牌：连续3天以上价格冻结（volume=0 或 high==low）→ score=50。"""
    # 120 根 K 线，最后 5 天 volume=0 且价格不变
    bars = _make_bars(115, close=100.0)
    frozen = _make_bars(5, close=100.0, volume=0)
    bars.extend(frozen)

    plugin = TimingFactorPlugin(fetcher=_StaticBarsFetcher(bars))
    target = TargetInfo(
        symbol="FREEZE", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    assert score.score == 50.0
    assert score.confidence == 0.3
    assert any("冻结" in w or "停牌" in w for w in score.warnings)


def test_limit_up_down_high_equals_low_returns_neutral():
    """一字板：连续3天以上 high==low → score=50。"""
    bars = _make_bars(115, close=100.0)
    # 一字涨停：high=low=open=close
    limit_up = [
        OHLCV(date=str(20240116 + i), open=100, high=100, low=100, close=100, volume=500)
        for i in range(5)
    ]
    bars.extend(limit_up)

    plugin = TimingFactorPlugin(fetcher=_StaticBarsFetcher(bars))
    target = TargetInfo(
        symbol="LIMIT", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    assert score.score == 50.0
    assert score.confidence == 0.3
    assert any("冻结" in w or "停牌" in w for w in score.warnings)


def test_no_false_positive_for_normal_data():
    """正常波动数据不应触发冻结检测。"""
    bars = _make_bars(120, close=100.0, high=105.0, low=95.0)
    plugin = TimingFactorPlugin(fetcher=_StaticBarsFetcher(bars))
    target = TargetInfo(
        symbol="NORMAL", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    assert score.score != 50.0
    assert not any("冻结" in w or "停牌" in w for w in score.warnings)


def test_all_zero_close_no_zero_division():
    """所有收盘价为 0（极端边界）→ 不应抛出 ZeroDivisionError。"""
    bars = _make_bars(120, close=0.0)
    plugin = TimingFactorPlugin(fetcher=_StaticBarsFetcher(bars))
    target = TargetInfo(
        symbol="ZERO", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    # 不应崩溃，应返回安全默认值
    assert 0.0 <= score.score <= 100.0


# ──────────────────────────────────────────────────────────────
# Test 2: New stock with insufficient data (< 60 days)
# ──────────────────────────────────────────────────────────────

def test_new_stock_confidence_zero():
    """新股数据不足 60 个交易日 → confidence 必须为 0.0。"""
    bars = _make_bars(30, close=100.0)
    plugin = TimingFactorPlugin(fetcher=_StaticBarsFetcher(bars))
    target = TargetInfo(
        symbol="NEW", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    assert score.score == 50.0
    assert score.confidence == 0.0
    assert any("不足" in w for w in score.warnings)


def test_exactly_60_days_is_sufficient():
    """刚好 60 天数据应正常计算，confidence > 0。"""
    bars = _make_bars(60, close=100.0, high=105.0, low=95.0)
    plugin = TimingFactorPlugin(fetcher=_StaticBarsFetcher(bars))
    target = TargetInfo(
        symbol="EDGE60", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    assert score.confidence > 0.0
    assert score.score != 50.0 or not any("不足" in w for w in score.warnings)


# ──────────────────────────────────────────────────────────────
# Test 3: ATR extreme volatility — physical limiter
# ──────────────────────────────────────────────────────────────

def test_atr_extreme_tear_clamped_by_max_mult():
    """ATR 极端撕裂时，atr_max_mult=2.0 物理限位器必须生效。

    构造每天 high=500, low=20（相对 close=100 波动率 480%），
    若限位器失效，volatility_factor 将爆炸到数百倍，
    导致 ideal_band/acceptable_band 异常扩大，score 可能超出 [0,100]。
    """
    bars = _make_bars(
        120,
        close=100.0,
        high=500.0,   # ATR 会被撑到极大
        low=20.0,
    )
    plugin = TimingFactorPlugin(fetcher=_StaticBarsFetcher(bars))
    target = TargetInfo(
        symbol="VOLATILE", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    # 无论 ATR 多夸张，最终分数必须在物理边界内
    assert 0.0 <= score.score <= 100.0
    # ATR ratio 应被记录在 details 中
    assert "atr_ratio" in score.details


def test_score_bias_atr_clamp_directly():
    """直接调用 _score_bias，验证极高 atr_ratio 下分数不越界。"""
    plugin = TimingFactorPlugin()

    # atr_ratio = 1.0 (100%)，baseline = 0.015
    # raw volatility_factor = 1 + (1.0 - 0.015)/0.015 ≈ 66.7
    # 若未 clamp 则 band 会异常扩大
    score, warnings = plugin._score_bias(
        bias=0.02,
        trend_slope=0.01,
        atr_ratio=1.0,
        timing_cfg={
            "ideal_band": 0.02,
            "acceptable_band": 0.05,
            "slope_veto_threshold": -0.03,
            "max_bonus": 10.0,
            "max_penalty": -40.0,
            "bullish_ref": 0.02,
            "atr_baseline": 0.015,
            "atr_k": 1.0,
            "atr_min_mult": 0.5,
            "atr_max_mult": 2.0,
        },
    )

    assert 0.0 <= score <= 100.0
    # 由于 atr_ratio 极高，volatility_factor 应被限制到 2.0
    # ideal_band = 0.02 * 2.0 = 0.04
    # acceptable_band = 0.05 * 2.0 = 0.10
    # bias=0.02 落在 ideal_band 内 → base_score=100
    # trend_slope=0.01 → bonus = min(0.01/0.02*10, 10) = 5.0
    # score ≈ 105 → clamped to 100
    assert score == 100.0


def test_score_bias_atr_extreme_negative_bias():
    """极高 ATR + 极大负 bias：验证分数不低于 0。"""
    plugin = TimingFactorPlugin()

    score, warnings = plugin._score_bias(
        bias=-0.5,  # 极大负偏差
        trend_slope=-0.02,  # 下坡但未触发 veto
        atr_ratio=1.0,
        timing_cfg={
            "ideal_band": 0.02,
            "acceptable_band": 0.05,
            "slope_veto_threshold": -0.03,
            "max_bonus": 10.0,
            "max_penalty": -40.0,
            "bullish_ref": 0.02,
            "atr_baseline": 0.015,
            "atr_k": 1.0,
            "atr_min_mult": 0.5,
            "atr_max_mult": 2.0,
        },
    )

    assert score >= 0.0
    assert score <= 100.0

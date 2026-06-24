from __future__ import annotations

from sentinel.mgfs.data.price_fetcher import OHLCV
from sentinel.mgfs.technical_strategy import AShareTechnicalStrategy


def _bar(
    index: int,
    close: float,
    *,
    open_price: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: int = 1_000_000,
) -> OHLCV:
    return OHLCV(
        date=f"2024{index + 1:04d}",
        open=open_price if open_price is not None else close,
        high=high if high is not None else close * 1.01,
        low=low if low is not None else close * 0.99,
        close=close,
        volume=volume,
    )


def _trend_then_pullback_bars() -> list[OHLCV]:
    bars: list[OHLCV] = []
    for i in range(70):
        bars.append(_bar(i, 88.0 + i * 0.35, volume=1_000_000))
    for i in range(70, 90):
        bars.append(_bar(i, 112.5 + (i - 70) * 0.08, volume=1_050_000))
    for i in range(90, 119):
        bars.append(_bar(i, 115.0 - (i - 90) * 0.18, volume=1_100_000))
    bars.append(_bar(119, 111.8, open_price=110.2, volume=1_900_000))
    return bars


def _trend_breakdown_bars() -> list[OHLCV]:
    bars: list[OHLCV] = []
    for i in range(90):
        bars.append(_bar(i, 82.0 + i * 0.35, volume=1_000_000))
    for i in range(90, 119):
        bars.append(_bar(i, 113.0 - (i - 90) * 0.08, volume=1_100_000))
    bars.append(_bar(119, 96.0, open_price=101.5, volume=2_500_000))
    return bars


def test_a_share_strategy_marks_pullback_recovery_as_entry_watch_not_trade_instruction():
    strategy = AShareTechnicalStrategy()

    report = strategy.analyze(_trend_then_pullback_bars())

    assert report.latest.entry_watch is True
    assert report.latest.entry_label == "entry_watch"
    assert "pullback_recovery" in report.latest.entry_tags
    assert report.latest.exit_watch is False
    assert report.latest.entry_zone_low < report.latest.entry_zone_high
    assert report.latest.stop_reference < report.latest.close
    assert report.latest.instruction_boundary == "research_only"


def test_a_share_strategy_marks_volume_breakdown_as_exit_risk():
    strategy = AShareTechnicalStrategy()

    report = strategy.analyze(_trend_breakdown_bars())

    assert report.latest.exit_watch is True
    assert report.latest.exit_label == "exit_risk"
    assert "volume_breakdown" in report.latest.exit_tags
    assert report.latest.entry_watch is False
    assert report.latest.stop_reference < report.latest.ma60


def test_analyze_as_of_ignores_future_bars_for_lookahead_guard():
    strategy = AShareTechnicalStrategy()
    prefix = _trend_then_pullback_bars()[:100]
    future_melt_up = [_bar(100 + i, 130.0 + i * 2.0) for i in range(20)]
    future_selloff = [_bar(100 + i, 80.0 - i * 1.5) for i in range(20)]

    report_a = strategy.analyze_as_of(prefix + future_melt_up, as_of_index=99)
    report_b = strategy.analyze_as_of(prefix + future_selloff, as_of_index=99)

    assert report_a.latest.close == report_b.latest.close
    assert report_a.latest.entry_watch == report_b.latest.entry_watch
    assert report_a.latest.exit_watch == report_b.latest.exit_watch
    assert report_a.latest.entry_tags == report_b.latest.entry_tags
    assert report_a.latest.exit_tags == report_b.latest.exit_tags

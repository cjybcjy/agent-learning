from datetime import datetime

from sentinel.analyzers.ranking import rank_snapshots
from sentinel.domain.models import HeatSnapshot, Market


def _snapshot(symbol: str, directed_heat: float, base_heat: float = 1.0) -> HeatSnapshot:
    return HeatSnapshot(
        timestamp=datetime(2026, 4, 29, 10, 0, 0),
        market=Market.A_SHARE,
        symbol=symbol,
        base_heat=base_heat,
        kol_multiplier=1.0,
        sentiment_score=0.5 if directed_heat > 0 else -0.5,
        directed_heat=directed_heat,
        change_pct=None,
        top_source="xueqiu",
        rank_bullish=None,
        rank_bearish=None,
        is_anomaly=False,
    )


def test_rank_assigns_bullish_and_bearish_ranks() -> None:
    snapshots = [
        _snapshot("A", directed_heat=5.0),
        _snapshot("B", directed_heat=3.0),
        _snapshot("C", directed_heat=-2.0),
        _snapshot("D", directed_heat=-4.0),
    ]

    result = rank_snapshots(snapshots, top_n=10)

    bullish = [s for s in result if s.rank_bullish is not None and s.directed_heat > 0]
    bearish = [s for s in result if s.rank_bearish is not None]

    assert bullish[0].symbol == "A"
    assert bullish[0].rank_bullish == 1
    assert bullish[1].symbol == "B"
    assert bearish[0].symbol == "D"
    assert bearish[0].rank_bearish == 1


def test_rank_top_n_limits_output() -> None:
    snapshots = [_snapshot(f"S{i}", directed_heat=float(i)) for i in range(1, 20)]
    result = rank_snapshots(snapshots, top_n=5)
    # Only top 5 bullish (no bearish in input)
    assert len(result) == 5
    assert result[0].symbol == "S19"


def test_rank_neutral_fallback_by_base_heat() -> None:
    snapshots = [
        HeatSnapshot(
            timestamp=datetime(2026, 4, 29, 10, 0, 0),
            market=Market.A_SHARE,
            symbol=f"N{i}",
            base_heat=float(i),
            kol_multiplier=1.0,
            sentiment_score=0.0,
            directed_heat=0.0,
            change_pct=None,
            top_source="xueqiu",
            rank_bullish=None,
            rank_bearish=None,
            is_anomaly=False,
        )
        for i in range(1, 6)
    ]

    result = rank_snapshots(snapshots, top_n=3)

    assert len(result) == 3
    assert result[0].symbol == "N5"
    assert result[0].rank_bullish == 1


def test_rank_empty_input() -> None:
    assert rank_snapshots([]) == []

from __future__ import annotations

from sentinel.domain.models import HeatSnapshot


def rank_snapshots(snapshots: list[HeatSnapshot], top_n: int = 10) -> list[HeatSnapshot]:
    """Assign bullish/bearish ranks and return top_n from each side.

    Ranking priority:
    1. Symbols WITH valid change_pct rank first, sorted by |Δ%| descending.
    2. "NEW" symbols (change_pct is None) follow, sorted by |H_score| descending.
    """
    if not snapshots:
        return []

    # Separate bullish (directed_heat > 0) and bearish (directed_heat < 0)
    bullish = [s for s in snapshots if s.directed_heat > 0]
    bearish = [s for s in snapshots if s.directed_heat < 0]
    neutral = [s for s in snapshots if s.directed_heat == 0]

    # Sort each group: Δ%-bearing first (by |Δ%|), then NEW (by |H_score|)
    bullish = _sort_with_change_priority(bullish)
    bearish = _sort_with_change_priority(bearish)

    # Assign ranks
    for i, s in enumerate(bullish, start=1):
        s.rank_bullish = i
    for i, s in enumerate(bearish, start=1):
        s.rank_bearish = i

    # If no sentiment data yet (all neutral), rank by |base_heat|
    if not bullish and not bearish:
        neutral = _sort_with_change_priority(neutral)
        for i, s in enumerate(neutral, start=1):
            s.rank_bullish = i
        return neutral[:top_n]

    result = bullish[:top_n] + bearish[:top_n]
    return result


def _sort_with_change_priority(items: list[HeatSnapshot]) -> list[HeatSnapshot]:
    """Sort: symbols with Δ% first (by |Δ%| desc), then NEW symbols (by |H_score| desc, ties by base_heat)."""
    with_change = [s for s in items if s.change_pct is not None]
    new_symbols = [s for s in items if s.change_pct is None]

    with_change.sort(key=lambda s: abs(s.change_pct or 0), reverse=True)
    new_symbols.sort(key=lambda s: (abs(s.directed_heat), s.base_heat), reverse=True)

    return with_change + new_symbols

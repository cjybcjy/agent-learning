from __future__ import annotations

from sentinel.domain.models import HeatSnapshot


def rank_snapshots(snapshots: list[HeatSnapshot], top_n: int = 10) -> list[HeatSnapshot]:
    """Assign bullish/bearish ranks and return top_n from each side merged."""
    if not snapshots:
        return []

    # Separate bullish (directed_heat > 0) and bearish (directed_heat < 0)
    bullish = sorted(
        [s for s in snapshots if s.directed_heat > 0],
        key=lambda s: s.directed_heat,
        reverse=True,
    )
    bearish = sorted(
        [s for s in snapshots if s.directed_heat < 0],
        key=lambda s: s.directed_heat,  # most negative first
    )
    # Neutral (directed_heat == 0) ranked by base_heat
    neutral = sorted(
        [s for s in snapshots if s.directed_heat == 0],
        key=lambda s: s.base_heat,
        reverse=True,
    )

    # Assign ranks
    for i, s in enumerate(bullish, start=1):
        s.rank_bullish = i
    for i, s in enumerate(bearish, start=1):
        s.rank_bearish = i

    # If no sentiment data yet (all neutral), rank by base_heat * kol_multiplier
    if not bullish and not bearish:
        for i, s in enumerate(neutral, start=1):
            s.rank_bullish = i
        return neutral[:top_n]

    # Return top_n from each side
    result = bullish[:top_n] + bearish[:top_n]
    return result

from __future__ import annotations

import statistics
from typing import Any

from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.mgfs.archetype_router import ArchetypeRouter
from sentinel.mgfs.data.valuation_fetcher import MockValuationFetcher, ValuationFetcher

settings = AppSettings()


def compute_percentiles(values: list[float]) -> tuple[float, float, float]:
    """Return (p10, p50, p90) for a list of numeric values.

    Filters out -1.0 sentinel values (missing data).
    """
    clean = [v for v in values if v >= 0]
    if not clean:
        return 0.0, 0.0, 0.0
    if len(clean) == 1:
        return clean[0], clean[0], clean[0]

    sorted_vals = sorted(clean)
    n = len(sorted_vals)

    def _percentile(p: float) -> float:
        idx = (n - 1) * p
        lower = int(idx)
        upper = min(lower + 1, n - 1)
        frac = idx - lower
        return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac

    return _percentile(0.10), _percentile(0.50), _percentile(0.90)


def build_valuation_band_data(
    symbol: str,
    market: Market,
    sector: str | None,
    fetcher: ValuationFetcher | None = None,
    years: int = 5,
) -> dict[str, Any] | None:
    """Build ECharts-compatible valuation band data.

    Uses ArchetypeRouter to determine primary metric (PE_TTM vs PB etc.)
    and fetches historical values with percentile bands.
    """
    router = ArchetypeRouter(settings.resolved_config_dir / "valuation_sector_routing.yaml")
    archetype = router.resolve_archetype(symbol, sector)
    metric = archetype.get("metrics", {}).get("primary", {}).get("name", "PE_TTM")

    if fetcher is None:
        from sentinel.mgfs.data.eastmoney_fetcher import EastmoneyValuationFetcher
        fetcher = EastmoneyValuationFetcher()

    try:
        values = fetcher.fetch_history(symbol, market, metric, years=years)
    except Exception:
        return None

    if not values:
        return None

    # Generate date labels (oldest first) - approximate trading days
    from datetime import datetime, timedelta
    end = datetime.now()
    start = end - timedelta(days=years * 365 + 30)
    dates: list[str] = []
    # Use simple calendar date generation; real data should align with values length
    current = start
    while len(dates) < len(values):
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    # Trim or pad to match values length
    dates = dates[:len(values)]

    p10, p50, p90 = compute_percentiles(values)

    metric_labels = {
        "PE_TTM": "PE-TTM",
        "PE": "PE",
        "PB": "PB",
        "PS": "PS",
        "PS_TTM": "PS-TTM",
    }

    return {
        "metric_name": metric,
        "metric_label": metric_labels.get(metric, metric),
        "dates": dates,
        "values": values,
        "p10": round(p10, 2),
        "p50": round(p50, 2),
        "p90": round(p90, 2),
    }

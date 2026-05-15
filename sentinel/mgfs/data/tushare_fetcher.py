from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime, timedelta
from typing import Any

from sentinel.domain.models import Market
from sentinel.mgfs.data.valuation_fetcher import ValuationFetcher

logger = logging.getLogger(__name__)


def _import_tushare() -> Any:
    import tushare as ts

    return ts


# Mapping from internal metric names to Tushare daily_basic field names
_METRIC_TO_FIELD: dict[str, str | None] = {
    "PE_TTM": "pe_ttm",
    "PE": "pe",
    "PB": "pb",
    "PS": "ps_ttm",
    "PS_TTM": "ps_ttm",
    "ROE": None,  # Not in daily_basic; would need fina_indicator
    "PEG": None,  # Must be computed
    "Dividend_Yield": "dv_ttm",
    "Operating_CF_Yield": None,
}


class TushareValuationFetcher(ValuationFetcher):
    """Fetch historical valuation metrics via Tushare Pro API.

    Anti-scraping / human-simulation measures:
    - Random delay (0.5-2.0 s) before each request
    - Exponential backoff with jitter on transient failures
    - Up to 3 retry attempts
    """

    MAX_RETRIES = 3
    BASE_DELAY = 0.5
    MAX_DELAY = 5.0

    def __init__(self, token: str | None = None, seed: int | None = None) -> None:
        self._token = token or os.environ.get("TUSHARE_TOKEN")
        self._pro: Any | None = None
        self._rng = random.Random(seed)

    def _get_pro(self) -> Any:
        if self._pro is not None:
            return self._pro

        try:
            ts = _import_tushare()
        except ImportError as exc:
            raise ImportError(
                "tushare is required for TushareValuationFetcher. "
                "Install it with: pip install tushare"
            ) from exc

        if not self._token:
            raise ValueError(
                "Tushare token is required. Set TUSHARE_TOKEN environment variable "
                "or pass token to the constructor."
            )

        self._pro = ts.pro_api(self._token)
        return self._pro

    def _random_delay(self) -> None:
        delay = self._rng.uniform(0.5, 2.0)
        time.sleep(delay)

    def _retry_with_backoff(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(self.MAX_RETRIES):
            try:
                self._random_delay()
                return func(*args, **kwargs)
            except Exception as exc:
                if attempt == self.MAX_RETRIES - 1:
                    raise
                delay = min(
                    self.BASE_DELAY * (2**attempt) + self._rng.uniform(0, 1),
                    self.MAX_DELAY,
                )
                logger.warning(
                    "Tushare request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    delay,
                    exc,
                )
                time.sleep(delay)
        return None  # unreachable, but satisfies type checker

    @staticmethod
    def _symbol_to_ts_code(symbol: str, market: Market) -> str:
        if market == Market.A_SHARE:
            # Shanghai: 6xxxxx, 5xxxxx (fund), 9xxxxx (B-share)
            # Shenzhen: 0xxxxx, 2xxxxx, 3xxxxx
            if symbol.startswith(("6", "5", "9")):
                return f"{symbol}.SH"
            return f"{symbol}.SZ"
        return symbol

    @staticmethod
    def _metric_to_field(metric: str) -> str:
        field = _METRIC_TO_FIELD.get(metric)
        if field is None:
            raise ValueError(
                f"Metric '{metric}' is not supported by Tushare daily_basic. "
                f"Supported: {list(_METRIC_TO_FIELD.keys())}"
            )
        return field

    def fetch_history(
        self, symbol: str, market: Market, metric: str, years: int = 5
    ) -> list[float]:
        pro = self._get_pro()
        ts_code = self._symbol_to_ts_code(symbol, market)
        field = self._metric_to_field(metric)

        end = datetime.now()
        start = end - timedelta(days=years * 365 + 30)

        def _fetch() -> Any:
            df = pro.daily_basic(
                ts_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                fields=f"trade_date,{field}",
            )
            return df

        df = self._retry_with_backoff(_fetch)

        if df is None or getattr(df, "empty", True):
            return []

        df = df.sort_values("trade_date")
        raw_values = list(df[field])

        import math

        result: list[float] = []
        for v in raw_values:
            if v is None or (isinstance(v, float) and math.isnan(v)):
                result.append(-1.0)
            else:
                result.append(float(v))
        return result

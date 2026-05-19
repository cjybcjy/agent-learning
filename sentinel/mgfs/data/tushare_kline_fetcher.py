from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime, timedelta
from typing import Any

from sentinel.domain.models import Market
from sentinel.mgfs.data.price_fetcher import OHLCV, PriceFetcher

logger = logging.getLogger(__name__)


def _import_tushare() -> Any:
    import tushare as ts

    return ts


class TushareKlineFetcher(PriceFetcher):
    """Fetch historical daily OHLCV via Tushare Pro API."""

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
                "tushare is required for TushareKlineFetcher. "
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
            if symbol.startswith(("6", "5", "9")):
                return f"{symbol}.SH"
            return f"{symbol}.SZ"
        return symbol

    def fetch_ohlcv(
        self, symbol: str, market: Market, days: int = 120
    ) -> list[OHLCV]:
        pro = self._get_pro()
        ts_code = self._symbol_to_ts_code(symbol, market)

        end = datetime.now()
        # Add buffer for weekends/holidays
        start = end - timedelta(days=int(days * 1.5) + 30)

        def _fetch() -> Any:
            return pro.daily(
                ts_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )

        df = self._retry_with_backoff(_fetch)

        if df is None or getattr(df, "empty", True):
            return []

        df = df.sort_values("trade_date")

        bars: list[OHLCV] = []
        for row in df.itertuples(index=False):
            bars.append(
                OHLCV(
                    date=str(getattr(row, "trade_date")),
                    open=float(getattr(row, "open")),
                    high=float(getattr(row, "high")),
                    low=float(getattr(row, "low")),
                    close=float(getattr(row, "close")),
                    volume=int(getattr(row, "vol")),
                )
            )

        # Return the most recent 'days' bars
        return bars[-days:] if len(bars) > days else bars

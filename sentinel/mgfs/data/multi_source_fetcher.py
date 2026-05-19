from __future__ import annotations

import logging
import os
from typing import Any

from sentinel.domain.models import Market
from sentinel.mgfs.data.price_fetcher import OHLCV, PriceFetcher

logger = logging.getLogger(__name__)

MIN_BAR_THRESHOLD = 60


class MultiSourceFetcher(PriceFetcher):
    """Composite fetcher that tries multiple sources in priority order."""

    def __init__(self, sources: list[PriceFetcher] | None = None) -> None:
        self._sources: list[PriceFetcher] = list(sources) if sources is not None else []
        self._health: dict[int, list[bool]] = {}

    @classmethod
    def default_chain(cls) -> MultiSourceFetcher:
        """Build a priority chain of fetchers."""
        sources: list[PriceFetcher] = []

        # 1. TushareKlineFetcher (if TUSHARE_TOKEN env var present)
        if os.environ.get("TUSHARE_TOKEN"):
            try:
                from sentinel.mgfs.data.tushare_kline_fetcher import TushareKlineFetcher

                sources.append(TushareKlineFetcher())
            except Exception:
                pass

        # 2. EastmoneyKlineFetcher
        try:
            from sentinel.mgfs.data.eastmoney_kline_fetcher import EastmoneyKlineFetcher

            sources.append(EastmoneyKlineFetcher())
        except Exception:
            pass

        # 3. TencentKlineFetcher
        try:
            from sentinel.mgfs.data.tencent_kline_fetcher import TencentKlineFetcher

            sources.append(TencentKlineFetcher())
        except Exception:
            pass

        # 4. SinaKlineFetcher
        try:
            from sentinel.mgfs.data.sina_kline_fetcher import SinaKlineFetcher

            sources.append(SinaKlineFetcher())
        except Exception:
            pass

        return cls(sources=sources)

    def _record_health(self, idx: int, success: bool) -> None:
        window = self._health.setdefault(idx, [])
        window.append(success)
        if len(window) > 10:
            window.pop(0)

    def _is_valid(self, bars: list[OHLCV], idx: int, symbol: str) -> bool:
        if len(bars) < MIN_BAR_THRESHOLD:
            logger.warning(
                "Data poisoning guard: source %d for %s returned only %d bars (min %d)",
                idx,
                symbol,
                len(bars),
                MIN_BAR_THRESHOLD,
            )
            return False

        prev_date: str | None = None
        for bar in bars:
            if (
                bar.open < 0
                or bar.high < 0
                or bar.low < 0
                or bar.close < 0
                or bar.volume < 0
            ):
                logger.warning(
                    "Data poisoning guard: source %d for %s has negative field in bar %s",
                    idx,
                    symbol,
                    bar.date,
                )
                return False

            if prev_date is not None and bar.date <= prev_date:
                logger.warning(
                    "Data poisoning guard: source %d for %s has non-monotonic dates: %s <= %s",
                    idx,
                    symbol,
                    bar.date,
                    prev_date,
                )
                return False
            prev_date = bar.date

        return True

    def fetch_ohlcv(
        self, symbol: str, market: Market, days: int = 120
    ) -> list[OHLCV]:
        last_exc: Exception | None = None
        n = len(self._sources)

        for idx, source in enumerate(self._sources):
            try:
                bars = source.fetch_ohlcv(symbol, market, days)
            except Exception as exc:
                last_exc = exc
                self._record_health(idx, False)
                continue

            if self._is_valid(bars, idx, symbol):
                self._record_health(idx, True)
                return bars

            self._record_health(idx, False)
            last_exc = RuntimeError(
                f"Source {idx} returned invalid data for {symbol}"
            )

        raise RuntimeError(f"All {n} sources failed for {symbol}") from last_exc

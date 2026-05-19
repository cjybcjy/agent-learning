from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests

from sentinel.domain.models import Market
from sentinel.mgfs.data.price_fetcher import OHLCV, PriceFetcher

logger = logging.getLogger(__name__)

_EASTMONEY_KLINE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={market_code}.{symbol}"
    "&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
    "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    "&klt=101&fqt=0&end=20500101&lmt={limit}"
)

# Browser-like headers for anti-bot evasion
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://quote.eastmoney.com/",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


class EastmoneyKlineFetcher(PriceFetcher):
    """Fetch daily OHLCV from Eastmoney public K-line API.

    Anti-bot / human-simulation measures:
    - Persistent Session with realistic browser headers
    - Random delay (0.5-3.0 s) before each request
    - Exponential backoff with jitter on transient failures
    - Up to 3 retry attempts for network and 5xx HTTP errors
    """

    MAX_RETRIES = 3
    BASE_DELAY = 1.0
    MAX_DELAY = 8.0

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._session = requests.Session()
        self._session.headers.update(_DEFAULT_HEADERS)

    def _random_delay(self) -> None:
        delay = self._rng.uniform(1.0, 4.0)
        time.sleep(delay)

    def _retry_with_backoff(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                self._random_delay()
                return func(*args, **kwargs)
            except requests.HTTPError as exc:
                last_exc = exc
                # Retry only on 5xx server errors
                resp = exc.response
                if resp is not None and resp.status_code < 500:
                    raise
                if attempt == self.MAX_RETRIES - 1:
                    raise
                delay = min(
                    self.BASE_DELAY * (2**attempt) + self._rng.uniform(0, 1),
                    self.MAX_DELAY,
                )
                logger.warning(
                    "Eastmoney HTTP %s (attempt %d/%d), retrying in %.1fs",
                    resp.status_code if resp is not None else "?",
                    attempt + 1,
                    self.MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt == self.MAX_RETRIES - 1:
                    raise
                delay = min(
                    self.BASE_DELAY * (2**attempt) + self._rng.uniform(0, 1),
                    self.MAX_DELAY,
                )
                logger.warning(
                    "Eastmoney request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    delay,
                    exc,
                )
                time.sleep(delay)
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _market_to_code(market: Market) -> str:
        if market == Market.A_SHARE:
            return "1"  # Shanghai default; Shenzhen handled in _symbol_to_secid
        if market == Market.HK:
            return "116"
        if market == Market.US:
            return "105"
        return "1"

    @staticmethod
    def _symbol_to_secid(symbol: str, market: Market) -> tuple[str, str]:
        """Return (market_code, symbol) for Eastmoney API."""
        if market == Market.A_SHARE:
            if symbol.startswith(("6", "5", "9")):
                return "1", symbol
            return "0", symbol
        if market == Market.HK:
            return "116", symbol
        if market == Market.US:
            return "105", symbol
        return "1", symbol

    def _do_request(self, url: str) -> dict[str, Any]:
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def fetch_ohlcv(
        self, symbol: str, market: Market, days: int = 120
    ) -> list[OHLCV]:
        market_code, clean_symbol = self._symbol_to_secid(symbol, market)
        url = _EASTMONEY_KLINE_URL.format(
            market_code=market_code,
            symbol=clean_symbol,
            limit=days,
        )

        data = self._retry_with_backoff(self._do_request, url)

        klines = data.get("data", {}).get("klines", []) if isinstance(data, dict) else []
        if not klines:
            return []

        bars: list[OHLCV] = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            bars.append(
                OHLCV(
                    date=parts[0],
                    open=float(parts[1]),
                    close=float(parts[2]),
                    high=float(parts[3]),
                    low=float(parts[4]),
                    volume=int(float(parts[5])),
                )
            )

        return bars[-days:] if len(bars) > days else bars

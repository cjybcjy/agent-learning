from __future__ import annotations

import json
import logging
from typing import Any

from sentinel.domain.models import Market
from sentinel.mgfs.data.anti_bot_adapter import AntiBotAdapter
from sentinel.mgfs.data.price_fetcher import OHLCV, PriceFetcher

logger = logging.getLogger(__name__)


class SinaKlineFetcher(PriceFetcher):
    """Fetch daily OHLCV from Sina's public K-line API."""

    def __init__(self, adapter: AntiBotAdapter | None = None) -> None:
        self._adapter = adapter if adapter is not None else AntiBotAdapter()

    def _symbol_to_code(self, symbol: str, market: Market) -> str:
        if market == Market.A_SHARE:
            prefix = "sh" if symbol.startswith(("6", "5", "9")) else "sz"
            return f"{prefix}{symbol}"
        return symbol

    def _parse(self, data: list[dict] | None) -> list[OHLCV]:
        if not data:
            return []

        bars: list[OHLCV] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                bars.append(
                    OHLCV(
                        date=str(item["day"]),
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=int(float(item["volume"])),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return bars

    def fetch_ohlcv(
        self, symbol: str, market: Market, days: int = 120
    ) -> list[OHLCV]:
        code = self._symbol_to_code(symbol, market)
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={code}&scale=240&datalen={days}"
        )
        resp = self._adapter.get(url)
        data = resp.json()
        bars = self._parse(data)
        if len(bars) > days:
            return bars[-days:]
        return bars

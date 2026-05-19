from __future__ import annotations

import json
import logging
from typing import Any

from sentinel.domain.models import Market
from sentinel.mgfs.data.anti_bot_adapter import AntiBotAdapter
from sentinel.mgfs.data.price_fetcher import OHLCV, PriceFetcher

logger = logging.getLogger(__name__)


class TencentKlineFetcher(PriceFetcher):
    """Fetch daily OHLCV from Tencent's public K-line API."""

    def __init__(self, adapter: AntiBotAdapter | None = None) -> None:
        self._adapter = adapter if adapter is not None else AntiBotAdapter()

    def _symbol_to_code(self, symbol: str, market: Market) -> str:
        if market == Market.A_SHARE:
            prefix = "sh" if symbol.startswith(("6", "5", "9")) else "sz"
            return f"{prefix}{symbol}"
        return symbol

    def _parse(self, data: dict[str, Any], code: str) -> list[OHLCV]:
        try:
            day_lines = data["data"][code]["day"]
        except (KeyError, TypeError):
            return []

        if not isinstance(day_lines, list):
            return []

        bars: list[OHLCV] = []
        for line in day_lines:
            if not isinstance(line, (list, tuple)) or len(line) < 6:
                continue
            try:
                bars.append(
                    OHLCV(
                        date=str(line[0]),
                        open=float(line[1]),
                        close=float(line[2]),
                        low=float(line[3]),
                        high=float(line[4]),
                        volume=int(float(line[5])),
                    )
                )
            except (ValueError, TypeError):
                continue
        return bars

    def fetch_ohlcv(
        self, symbol: str, market: Market, days: int = 120
    ) -> list[OHLCV]:
        code = self._symbol_to_code(symbol, market)
        url = (
            f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={code},day,20200101,20500101,{days}"
        )
        resp = self._adapter.get(url)
        data = resp.json()
        bars = self._parse(data, code)
        if len(bars) > days:
            return bars[-days:]
        return bars

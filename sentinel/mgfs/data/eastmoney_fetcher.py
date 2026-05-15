"""Eastmoney open API valuation fetcher — free, no token required.

Data source: 东方财富数据中心公开 API (datacenter-web.eastmoney.com)
Anti-scraping measures:
- Random delay (0.5-2.0 s) between requests
- User-Agent rotation
- Exponential backoff with jitter on failures
- Local disk cache to avoid repeated requests
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sentinel.domain.models import Market
from sentinel.mgfs.data.valuation_fetcher import ValuationFetcher

logger = logging.getLogger(__name__)

# Mapping from internal metric names to Eastmoney API field names
_METRIC_TO_FIELD: dict[str, str] = {
    "PE_TTM": "PE_TTM",
    "PE": "PE_LAR",
    "PB": "PB_MRQ",
    "PS": "PS_TTM",
    "PS_TTM": "PS_TTM",
    "PCF": "PCF_OCF_TTM",
}

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]


class EastmoneyValuationFetcher(ValuationFetcher):
    """Fetch historical valuation metrics via Eastmoney open API (free, no token).

    Anti-scraping / human-simulation measures:
    - Random delay (0.5-2.0 s) before each request
    - Rotating User-Agent headers
    - Exponential backoff with jitter on transient failures
    - Up to 3 retry attempts
    - Local JSON cache to avoid repeated API calls
    """

    MAX_RETRIES = 3
    BASE_DELAY = 0.5
    MAX_DELAY = 5.0
    API_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    PAGE_SIZE = 500

    def __init__(
        self,
        seed: int | None = None,
        cache_dir: Path | str | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        self._cache_dir = (
            Path(cache_dir) if cache_dir else Path.home() / ".cache" / "sentinel" / "eastmoney"
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _random_delay(self) -> None:
        delay = self._rng.uniform(0.5, 2.0)
        time.sleep(delay)

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._rng.choice(_USER_AGENTS),
            "Referer": "https://data.eastmoney.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def _retry_with_backoff(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                self._random_delay()
                return func(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt == self.MAX_RETRIES - 1:
                    raise last_exc
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
        return None  # unreachable, but satisfies type checker

    @staticmethod
    def _metric_to_field(metric: str) -> str:
        field = _METRIC_TO_FIELD.get(metric)
        if field is None:
            raise ValueError(
                f"Metric '{metric}' is not supported by Eastmoney API. "
                f"Supported: {list(_METRIC_TO_FIELD.keys())}"
            )
        return field

    def _cache_path(self, symbol: str, metric: str) -> Path:
        today = datetime.now().strftime("%Y%m%d")
        return self._cache_dir / f"{symbol}_{metric}_{today}.json"

    def _load_cache(self, symbol: str, metric: str) -> list[dict[str, Any]] | None:
        path = self._cache_path(symbol, metric)
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                logger.debug("Cache load failed for %s %s", symbol, metric)
        return None

    def _save_cache(self, symbol: str, metric: str, data: list[dict[str, Any]]) -> None:
        path = self._cache_path(symbol, metric)
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            logger.debug("Cache save failed for %s %s", symbol, metric)

    def _fetch_page(self, symbol: str, page: int) -> tuple[list[dict[str, Any]], int]:
        """Fetch one page of historical valuation data.

        Returns:
            (records_list, total_count)
        """
        import urllib.request

        params = (
            f"reportName=RPT_VALUEANALYSIS_DET"
            f"&columns=ALL"
            f"&filter=(SECURITY_CODE%3D%22{symbol}%22)"
            f"&pageNumber={page}"
            f"&pageSize={self.PAGE_SIZE}"
        )
        url = f"{self.API_BASE}?{params}"

        req = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        result = data.get("result", {})
        records = result.get("data", []) or []
        total = result.get("count", 0) or len(records)
        return records, total

    def _fetch_all(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch all pages of historical valuation data with caching."""
        cached = self._load_cache(symbol, "all")
        if cached is not None:
            logger.debug("Using cached data for %s", symbol)
            return cached

        all_records: list[dict[str, Any]] = []
        page = 1
        total = None

        while True:
            records, page_total = self._retry_with_backoff(self._fetch_page, symbol, page)
            if total is None:
                total = page_total
                logger.debug("Eastmoney: %s has %d total records", symbol, total)

            if not records:
                break

            all_records.extend(records)
            logger.debug("Fetched page %d (%d records) for %s", page, len(records), symbol)

            if len(all_records) >= total:
                break

            page += 1

        # Sort by trade date ascending (oldest first)
        all_records.sort(key=lambda r: r.get("TRADE_DATE", ""))
        self._save_cache(symbol, "all", all_records)
        return all_records

    def fetch_history(
        self, symbol: str, market: Market, metric: str, years: int = 5
    ) -> list[float]:
        """Fetch historical daily values for a valuation metric.

        Returns:
            List of daily metric values (most recent last).
        """
        field = self._metric_to_field(metric)
        records = self._fetch_all(symbol)

        if not records:
            logger.warning("No historical data returned for %s", symbol)
            return []

        # Filter to requested years
        cutoff_date = datetime.now().replace(year=datetime.now().year - years)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")

        values: list[float] = []
        for record in records:
            trade_date = record.get("TRADE_DATE", "")
            if trade_date and trade_date < cutoff_str:
                continue

            raw = record.get(field)
            if raw is None:
                values.append(-1.0)
            else:
                try:
                    val = float(raw)
                    values.append(val)
                except (ValueError, TypeError):
                    values.append(-1.0)

        return values

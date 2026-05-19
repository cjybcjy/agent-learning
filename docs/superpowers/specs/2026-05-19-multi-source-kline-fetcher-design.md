# Multi-Source K-line Fetcher with Anti-Bot Evasion

## Date
2026-05-19

## Context
The `TimingFactorPlugin` currently depends on a single `PriceFetcher` (Eastmoney or Tushare). When that source is rate-limited, blocked by anti-bot measures, or returns network errors, the timing module crashes, triggering the orchestrator's SOFT_VETO and downgrading the stock to Hold/Watch. While this is safe, it means we lose timing signals for otherwise healthy stocks simply because one data source is unavailable.

This design adds multiple fallback public API sources and enhanced anti-bot capabilities to maximize data source availability.

## Goals
1. **Multi-source resilience**: Chain Tushare → Eastmoney → Tencent → Sina; automatically degrade on failure.
2. **Anti-bot evasion**: Human-like request pacing, UA rotation, cookie persistence, and `curl_cffi` for Cloudflare bypass.
3. **Data poisoning guard**: Even HTTP 200 responses with invalid/insufficient data must trigger fallback.
4. **Zero plugin intrusion**: `TimingFactorPlugin` requires no code changes; dependency injection handles everything.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              TimingFactorPlugin (no changes)                 │
│                      ↓ inject                               │
│              MultiSourceFetcher                              │
│   ┌─────────┬─────────┬─────────────┬─────────────┐         │
│   │ Tushare │Eastmoney│    Tencent   │    Sina      │         │
│   │KlineFetcher     │KlineFetcher │KlineFetcher │KlineFetcher│
│   │ (token) │ (public)│   (public)  │   (public)  │         │
│   └────┬────┴────┬────┴──────┬──────┴──────┬──────┘         │
│        │         │           │              │                │
│   ┌────┴─────────┴───────────┴──────────────┴────┐          │
│   │         AntiBotAdapter (optional wrap)        │          │
│   │  • UA pool  • Human delay  • curl_cffi        │          │
│   └───────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. AntiBotAdapter

HTTP request wrapper providing anti-bot capabilities. Used internally by fetchers that scrape public APIs.

```python
class AntiBotAdapter:
    def __init__(self, use_curl_cffi: bool = False) -> None: ...
    def get(self, url: str, **kwargs) -> requests.Response: ...
```

**Capabilities:**
- **UA rotation pool**: 15+ real browser UAs (Chrome/Firefox/Safari on Windows/macOS/Android). Each request randomly selects one and syncs correlated headers (`Sec-Ch-Ua`, `Accept-Language`).
- **Human-like delay**: Not uniform random. Simulates real browsing:
  - Cold start: 2-5s (opening webpage)
  - Continuous browsing: 0.8-2.5s (flipping through charts)
  - Long pause: every 5-8 requests, pause 5-10s (reading/analyzing)
  - Adaptive acceleration: after 10 consecutive successes, allow 0.5-1.5s
  - Post-ban slowdown: on 403/429, double base delay for 60s
- **Cookie persistence**: Shared `requests.Session` (or `curl_cffi.requests.Session`) maintains cookies across requests.
- **curl_cffi fallback**: Standard `requests` is the default (lightweight, fast). If a `CloudflareChallengeError` or repeated 403 occurs, transparently switch to `curl_cffi` which mimics Chrome's TLS fingerprint.

### 2. TencentKlineFetcher

```python
class TencentKlineFetcher(PriceFetcher):
    """Fetch daily OHLCV from Tencent Finance public API."""
```

- **Endpoint**: `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get`
- **Parameters**: `param={market}{symbol},day,{start},{end},{limit}`
- **Market codes**: `sh` (Shanghai), `sz` (Shenzhen)
- **Response format**: `data[symbol][day]` = `[[date, open, close, low, high, volume], ...]`
- **Features**: Supports forward-adjusted prices (`fq` endpoint)
- **Limit**: 320 bars per request; paginate if needed

### 3. SinaKlineFetcher

```python
class SinaKlineFetcher(PriceFetcher):
    """Fetch daily OHLCV from Sina Finance public API."""
```

- **Endpoint**: `https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData`
- **Parameters**: `symbol={market}{symbol}&scale=240&datalen={limit}`
- **Market codes**: `sh` (Shanghai), `sz` (Shenzhen)
- **Response format**: JSON array `[{day, open, high, low, close, volume}, ...]`
- **Features**: No hard per-request limit; extremely stable
- **Limit**: No price adjustment (unadjusted data only)

### 4. MultiSourceFetcher

```python
class MultiSourceFetcher(PriceFetcher):
    def __init__(self, sources: list[PriceFetcher] | None = None) -> None: ...

    @classmethod
    def default_chain(cls) -> MultiSourceFetcher: ...

    def fetch_ohlcv(self, symbol: str, market: Market, days: int = 120) -> list[OHLCV]: ...
```

**Fallback chain** (default):
1. `TushareKlineFetcher` — requires `TUSHARE_TOKEN`
2. `EastmoneyKlineFetcher` — public API
3. `TencentKlineFetcher` — public API
4. `SinaKlineFetcher` — public API

**Behavior:**
- Iterates through sources in priority order.
- Any exception (connection, timeout, HTTP error) triggers degradation to next source.
- **Data poisoning control** (user-enforced guard): After HTTP 200, validate returned `list[OHLCV]`:
  - Minimum length check: `len(bars) >= max(60, days * 0.5)` (must satisfy MA60 computation threshold)
  - Field sanity check: all OHLCV fields are numeric and non-negative
  - Chronological order check: dates are monotonically increasing
  - If any check fails, treat as source failure and degrade.
- **Health tracking**: Each source maintains a sliding window of last 10 requests. After 3 consecutive failures, the source is temporarily demoted to the end of the chain. On next success, it recovers to its original position.
- **All sources exhausted**: Raises `RuntimeError` with the last underlying exception. `TimingFactorPlugin` catches this and produces a system-failure `FactorScore`, which triggers the orchestrator's SOFT_VETO (already implemented in the 2026-05-19 hotfix).

**Integration:**
```python
# In get_orchestrator() factory:
fetcher = MultiSourceFetcher.default_chain()
timing_plugin = TimingFactorPlugin(fetcher=fetcher)
```

`TimingFactorPlugin` requires **zero code changes**.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Tushare token missing | `TushareKlineFetcher` init raises `ValueError`; `MultiSourceFetcher` skips it automatically |
| Eastmoney returns 403 | `AntiBotAdapter` triggers curl_cffi bypass; if still failing, degrade to Tencent |
| Tencent returns HTTP 200 with `{"msg": "sys_error"}` | Data poisoning control catches it (empty/invalid bars); degrade to Sina |
| Sina returns 3 days of data for a 120-day request | Minimum length check fails; all sources exhausted → `RuntimeError` → SOFT_VETO |
| Network completely down | All sources fail → `RuntimeError` → orchestrator SOFT_VETO → Hold/Watch |

## Testing Strategy (TDD)

| Test File | Coverage |
|-----------|----------|
| `test_anti_bot_adapter.py` | UA rotation, non-uniform delay distribution, curl_cffi fallback on 403, adaptive slowdown |
| `test_tencent_kline_fetcher.py` | JSON parsing, empty data, pagination, field mapping to OHLCV |
| `test_sina_kline_fetcher.py` | JSON parsing, empty data, unadjusted data handling |
| `test_multi_source_fetcher.py` | Fallback chain order, all-fail exception, insufficient-data degradation, health-check demotion |

**Red-Green sequence:**
1. Red: `test_multi_source_fetcher.py` — mock fetchers that sequentially fail/return bad data.
2. Green: Implement `MultiSourceFetcher`.
3. Red: `test_anti_bot_adapter.py` — mock HTTP responses with 403, verify curl_cffi switch.
4. Green: Implement `AntiBotAdapter`.
5. Red: `test_tencent_kline_fetcher.py` — mock Tencent API JSON.
6. Green: Implement `TencentKlineFetcher`.
7. Red: `test_sina_kline_fetcher.py` — mock Sina API JSON.
8. Green: Implement `SinaKlineFetcher`.
9. Refactor: Ensure all tests pass, no duplication.

## Files to Create/Modify

**New files:**
- `sentinel/mgfs/data/anti_bot_adapter.py`
- `sentinel/mgfs/data/tencent_kline_fetcher.py`
- `sentinel/mgfs/data/sina_kline_fetcher.py`
- `sentinel/mgfs/data/multi_source_fetcher.py`
- `tests/test_anti_bot_adapter.py`
- `tests/test_tencent_kline_fetcher.py`
- `tests/test_sina_kline_fetcher.py`
- `tests/test_multi_source_fetcher.py`

**Modified files:**
- `sentinel/web/dependencies.py` (or wherever `get_orchestrator()` lives) — inject `MultiSourceFetcher.default_chain()`

## Dependencies

- `curl_cffi` (optional) — for Cloudflare/TLS fingerprint bypass. Falls back to standard `requests` if not installed.
- `responses` (dev) — for HTTP mocking in tests.

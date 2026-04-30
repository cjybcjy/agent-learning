# Sentinel

Market sentiment anomaly collection system for A shares, Hong Kong equities, US equities, and crypto markets.

## Phase 1 Scope

This phase provides:
- Python package skeleton
- YAML-based runtime configuration
- DuckDB schema bootstrap
- Typer CLI command that stores one synthetic snapshot

## Phase 2 Scope

This phase adds:
- Collector plugin system with `BaseCollector` ABC and `CollectorRegistry`
- Async HTTP adapter (`aiohttp`)
- Representative market collectors: `xueqiu` (A shares), `reddit_stocks` (US), `coingecko` (crypto)
- `StaticCollector` for deterministic local testing
- Pipeline replaced with async collector execution

## Collector Development

Representative collectors included:
- `xueqiu` for A shares
- `reddit_stocks` for US equities
- `coingecko` for crypto
- `synthetic` for deterministic local testing

Collector modules expose parser helpers so tests can validate payload handling without making live network calls.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python main.py --market A股
```

Expected output:

```text
collected 1 mention for A股
```

## Test

```bash
pytest tests -v
```
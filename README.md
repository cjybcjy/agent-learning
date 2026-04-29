# Sentinel

Market sentiment anomaly collection system for A shares, Hong Kong equities, US equities, and crypto markets.

## Phase 1 Scope

This phase provides:
- Python package skeleton
- YAML-based runtime configuration
- DuckDB schema bootstrap
- Typer CLI command that stores one synthetic snapshot

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
stored 1 snapshot for A股
```

## Test

```bash
pytest tests -v
```
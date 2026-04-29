from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS heat_metrics (
    timestamp TIMESTAMP NOT NULL,
    market VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    base_heat DOUBLE NOT NULL,
    kol_multiplier DOUBLE NOT NULL,
    sentiment_score DOUBLE NOT NULL,
    directed_heat DOUBLE NOT NULL,
    change_pct DOUBLE,
    top_source VARCHAR,
    rank_bullish INTEGER,
    rank_bearish INTEGER,
    is_anomaly BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (timestamp, market, symbol)
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> duckdb.DuckDBPyConnection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(self.path))

    def bootstrap(self) -> None:
        con = self.connect()
        try:
            con.execute(SCHEMA_SQL)
        finally:
            con.close()

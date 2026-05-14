from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.storage.db import Database

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trend_metrics (
    symbol VARCHAR(50) NOT NULL,
    market VARCHAR(20) NOT NULL,
    metric_name VARCHAR(50) NOT NULL,
    value DOUBLE NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, market, metric_name, recorded_at)
);

CREATE TABLE IF NOT EXISTS safety_metrics (
    symbol VARCHAR(50) NOT NULL,
    market VARCHAR(20) NOT NULL,
    metric_name VARCHAR(50) NOT NULL,
    value DOUBLE NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, market, metric_name, recorded_at)
);
"""


class MetricsAggregator:
    def __init__(self, database: Database, mock_mode: bool = False) -> None:
        self.database = database
        self.mock_mode = mock_mode

    def bootstrap(self) -> None:
        con = self.database.connect()
        try:
            con.execute(SCHEMA_SQL)
        finally:
            con.close()

    def insert_trend_metric(
        self,
        target: TargetInfo,
        metric_name: str,
        value: float,
        recorded_at: datetime | None = None,
    ) -> None:
        if recorded_at is None:
            recorded_at = datetime.now(tz=timezone.utc)
        con = self.database.connect()
        try:
            con.execute(
                """
                INSERT INTO trend_metrics
                (symbol, market, metric_name, value, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (symbol, market, metric_name, recorded_at)
                DO UPDATE SET value = EXCLUDED.value
                """,
                [target.symbol, target.market.value, metric_name, value, recorded_at],
            )
        finally:
            con.close()

    def get_latest_trend_metric(
        self, target: TargetInfo, metric_name: str
    ) -> dict[str, Any] | None:
        if self.mock_mode:
            return {
                "symbol": target.symbol,
                "market": target.market.value,
                "metric_name": metric_name,
                "value": round(random.uniform(30.0, 90.0), 2),
                "recorded_at": datetime.now(tz=timezone.utc),
            }

        con = self.database.connect()
        try:
            row = con.execute(
                """
                SELECT * FROM trend_metrics
                WHERE symbol = ? AND market = ? AND metric_name = ?
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                [target.symbol, target.market.value, metric_name],
            ).fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in con.description]
            return dict(zip(columns, row))
        finally:
            con.close()

    def insert_safety_metric(
        self,
        target: TargetInfo,
        metric_name: str,
        value: float,
        recorded_at: datetime | None = None,
    ) -> None:
        if recorded_at is None:
            recorded_at = datetime.now(tz=timezone.utc)
        con = self.database.connect()
        try:
            con.execute(
                """
                INSERT INTO safety_metrics
                (symbol, market, metric_name, value, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (symbol, market, metric_name, recorded_at)
                DO UPDATE SET value = EXCLUDED.value
                """,
                [target.symbol, target.market.value, metric_name, value, recorded_at],
            )
        finally:
            con.close()

    def get_latest_safety_metric(
        self, target: TargetInfo, metric_name: str
    ) -> dict[str, Any] | None:
        if self.mock_mode:
            return {
                "symbol": target.symbol,
                "market": target.market.value,
                "metric_name": metric_name,
                "value": round(random.uniform(30.0, 90.0), 2),
                "recorded_at": datetime.now(tz=timezone.utc),
            }

        con = self.database.connect()
        try:
            row = con.execute(
                """
                SELECT * FROM safety_metrics
                WHERE symbol = ? AND market = ? AND metric_name = ?
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                [target.symbol, target.market.value, metric_name],
            ).fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in con.description]
            return dict(zip(columns, row))
        finally:
            con.close()

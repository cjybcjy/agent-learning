from __future__ import annotations

import json
import random
from datetime import date, datetime, timezone
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

CREATE TABLE IF NOT EXISTS metric_source_audit (
    symbol VARCHAR(50) NOT NULL,
    market VARCHAR(20) NOT NULL,
    metric_name VARCHAR(50) NOT NULL,
    target_table VARCHAR(50) NOT NULL,
    source VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    source_url VARCHAR,
    financial_items_json VARCHAR,
    calculation_hint VARCHAR,
    recorded_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, market, metric_name, target_table, recorded_at)
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
        stored_recorded_at = _recorded_at_for_storage(recorded_at)
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
                [
                    target.symbol,
                    target.market.value,
                    metric_name,
                    value,
                    stored_recorded_at,
                ],
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
            result = con.execute(
                """
                SELECT * FROM trend_metrics
                WHERE symbol = ? AND market = ? AND metric_name = ?
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                [target.symbol, target.market.value, metric_name],
            )
            columns = [desc[0] for desc in result.description]
            row = result.fetchone()
            if row is None:
                return None
            return _restore_recorded_at(dict(zip(columns, row)))
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
        stored_recorded_at = _recorded_at_for_storage(recorded_at)
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
                [
                    target.symbol,
                    target.market.value,
                    metric_name,
                    value,
                    stored_recorded_at,
                ],
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
            result = con.execute(
                """
                SELECT * FROM safety_metrics
                WHERE symbol = ? AND market = ? AND metric_name = ?
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                [target.symbol, target.market.value, metric_name],
            )
            columns = [desc[0] for desc in result.description]
            row = result.fetchone()
            if row is None:
                return None
            return _restore_recorded_at(dict(zip(columns, row)))
        finally:
            con.close()

    def record_metric_source(
        self,
        target: TargetInfo,
        *,
        metric_name: str,
        target_table: str,
        source: str,
        as_of: date,
        recorded_at: datetime,
        source_url: str | None = None,
        financial_items: list[str] | None = None,
        calculation_hint: str | None = None,
    ) -> None:
        stored_recorded_at = _recorded_at_for_storage(recorded_at)
        con = self.database.connect()
        try:
            con.execute(
                """
                INSERT INTO metric_source_audit
                (
                    symbol, market, metric_name, target_table, source, as_of,
                    source_url, financial_items_json, calculation_hint, recorded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol, market, metric_name, target_table, recorded_at)
                DO UPDATE SET
                    source = EXCLUDED.source,
                    as_of = EXCLUDED.as_of,
                    source_url = EXCLUDED.source_url,
                    financial_items_json = EXCLUDED.financial_items_json,
                    calculation_hint = EXCLUDED.calculation_hint
                """,
                [
                    target.symbol,
                    target.market.value,
                    metric_name,
                    target_table,
                    source,
                    as_of,
                    source_url,
                    json.dumps(financial_items or [], ensure_ascii=False),
                    calculation_hint,
                    stored_recorded_at,
                ],
            )
        finally:
            con.close()

    def get_metric_source_audit(
        self,
        target: TargetInfo,
        metric_name: str | None = None,
    ) -> list[dict[str, Any]]:
        con = self.database.connect()
        try:
            params: list[Any] = [target.symbol, target.market.value]
            metric_filter = ""
            if metric_name is not None:
                metric_filter = "AND metric_name = ?"
                params.append(metric_name)
            result = con.execute(
                f"""
                SELECT
                    symbol, market, metric_name, target_table, source, as_of,
                    source_url, financial_items_json, calculation_hint, recorded_at
                FROM metric_source_audit
                WHERE symbol = ? AND market = ?
                {metric_filter}
                ORDER BY recorded_at DESC, metric_name ASC
                """,
                params,
            )
            columns = [desc[0] for desc in result.description]
            return [
                _restore_recorded_at(dict(zip(columns, row)))
                for row in result.fetchall()
            ]
        finally:
            con.close()


def _recorded_at_for_storage(recorded_at: Any) -> Any:
    if isinstance(recorded_at, datetime) and recorded_at.tzinfo is not None:
        return recorded_at.astimezone(timezone.utc).replace(tzinfo=None)
    return recorded_at


def _restore_recorded_at(row: dict[str, Any]) -> dict[str, Any]:
    recorded_at = row.get("recorded_at")
    if isinstance(recorded_at, datetime) and recorded_at.tzinfo is None:
        row["recorded_at"] = recorded_at.replace(tzinfo=timezone.utc)
    return row

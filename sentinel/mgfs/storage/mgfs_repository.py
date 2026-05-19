from __future__ import annotations

import json
from typing import Any

from sentinel.domain.models import Market
from sentinel.mgfs.orchestrator import InvestmentDecision
from sentinel.storage.db import Database

__all__ = ["MGFSRepository"]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mgfs_decisions (
    evaluated_at TIMESTAMP NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    market VARCHAR(20) NOT NULL,
    asset_class VARCHAR(20) NOT NULL,
    sector VARCHAR(50),
    moat_score DOUBLE,
    token_score DOUBLE,
    financials_score DOUBLE,
    raw_total DOUBLE,
    policy_multiplier DOUBLE,
    final_score DOUBLE,
    rating VARCHAR(20),
    alert_level VARCHAR(20),
    circuit_breakers_triggered JSON,
    factor_details JSON,
    PRIMARY KEY (evaluated_at, symbol, market)
);

CREATE TABLE IF NOT EXISTS mgfs_pipeline_batches (
    batch_id VARCHAR(32) PRIMARY KEY,
    triggered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(16) NOT NULL,
    total_count INTEGER DEFAULT 0,
    strong_buy_count INTEGER DEFAULT 0,
    error_log TEXT
);

CREATE TABLE IF NOT EXISTS mgfs_pipeline_results (
    batch_id VARCHAR(32) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    name VARCHAR(32) NOT NULL,
    moat_score DOUBLE NOT NULL,
    valuation_percentile DOUBLE NOT NULL,
    timing_score DOUBLE NOT NULL,
    final_score DOUBLE NOT NULL,
    rating VARCHAR(16) NOT NULL,
    action TEXT NOT NULL,
    PRIMARY KEY (batch_id, symbol),
    FOREIGN KEY (batch_id) REFERENCES mgfs_pipeline_batches(batch_id)
);
"""


class MGFSRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def bootstrap(self) -> None:
        con = self.database.connect()
        try:
            con.execute(SCHEMA_SQL)
        finally:
            con.close()

    def save_decision(self, decision: InvestmentDecision) -> None:
        con = self.database.connect()
        try:
            con.execute(
                """
                INSERT INTO mgfs_decisions (
                    evaluated_at, symbol, market, asset_class, sector,
                    moat_score, token_score, financials_score,
                    raw_total, policy_multiplier, final_score,
                    rating, alert_level, circuit_breakers_triggered, factor_details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (evaluated_at, symbol, market) DO UPDATE SET
                    asset_class = excluded.asset_class,
                    sector = excluded.sector,
                    moat_score = excluded.moat_score,
                    token_score = excluded.token_score,
                    financials_score = excluded.financials_score,
                    raw_total = excluded.raw_total,
                    policy_multiplier = excluded.policy_multiplier,
                    final_score = excluded.final_score,
                    rating = excluded.rating,
                    alert_level = excluded.alert_level,
                    circuit_breakers_triggered = excluded.circuit_breakers_triggered,
                    factor_details = excluded.factor_details
                """,
                [
                    decision.generated_at,
                    decision.target.symbol,
                    decision.target.market.value,
                    decision.target.asset_class,
                    decision.target.sector,
                    _extract_factor_score(decision, "moat"),
                    _extract_factor_score(decision, "token_metrics"),
                    _extract_factor_score(decision, "financials"),
                    decision.raw_total,
                    decision.policy_multiplier,
                    decision.final_score,
                    decision.rating,
                    decision.alert_level.value,
                    json.dumps(decision.circuit_breakers_triggered),
                    json.dumps(
                        {
                            k: {
                                "score": v.score,
                                "normalized": v.normalized_score,
                                "details": v.details,
                            }
                            for k, v in decision.factor_scores.items()
                        }
                    ),
                ],
            )
        finally:
            con.close()

    def get_decisions_for_symbol(
        self, symbol: str, market: Market
    ) -> list[dict[str, Any]]:
        con = self.database.connect()
        try:
            rows = con.execute(
                """
                SELECT * FROM mgfs_decisions
                WHERE symbol = ? AND market = ?
                ORDER BY evaluated_at DESC
                """,
                [symbol, market.value],
            ).fetchall()
            columns = [desc[0] for desc in con.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Pipeline batch management
    # ------------------------------------------------------------------

    def create_pipeline_batch(self, batch_id: str, status: str) -> None:
        con = self.database.connect()
        try:
            con.execute(
                """
                INSERT INTO mgfs_pipeline_batches (batch_id, status)
                VALUES (?, ?)
                """,
                [batch_id, status],
            )
        finally:
            con.close()

    def update_pipeline_batch_status(
        self,
        batch_id: str,
        status: str,
        total_count: int | None = None,
        strong_buy_count: int | None = None,
        error_log: str | None = None,
    ) -> None:
        con = self.database.connect()
        try:
            fields = ["status = ?"]
            params: list[Any] = [status]
            if total_count is not None:
                fields.append("total_count = ?")
                params.append(total_count)
            if strong_buy_count is not None:
                fields.append("strong_buy_count = ?")
                params.append(strong_buy_count)
            if error_log is not None:
                fields.append("error_log = ?")
                params.append(error_log)
            params.append(batch_id)
            sql = f"UPDATE mgfs_pipeline_batches SET {', '.join(fields)} WHERE batch_id = ?"
            con.execute(sql, params)
        finally:
            con.close()

    def get_pipeline_batch(self, batch_id: str) -> dict[str, Any] | None:
        con = self.database.connect()
        try:
            row = con.execute(
                "SELECT * FROM mgfs_pipeline_batches WHERE batch_id = ?",
                [batch_id],
            ).fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in con.description]
            return dict(zip(columns, row))
        finally:
            con.close()

    def list_pipeline_batches(self, limit: int = 50) -> list[dict[str, Any]]:
        con = self.database.connect()
        try:
            rows = con.execute(
                """
                SELECT * FROM mgfs_pipeline_batches
                ORDER BY triggered_at DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()
            columns = [desc[0] for desc in con.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            con.close()

    def save_pipeline_result(
        self,
        batch_id: str,
        symbol: str,
        name: str,
        moat_score: float,
        valuation_percentile: float,
        timing_score: float,
        final_score: float,
        rating: str,
        action: str,
    ) -> None:
        con = self.database.connect()
        try:
            con.execute(
                """
                INSERT INTO mgfs_pipeline_results
                (batch_id, symbol, name, moat_score, valuation_percentile,
                 timing_score, final_score, rating, action)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    batch_id, symbol, name, moat_score,
                    valuation_percentile, timing_score, final_score,
                    rating, action,
                ],
            )
        finally:
            con.close()

    def get_pipeline_results(self, batch_id: str) -> list[dict[str, Any]]:
        con = self.database.connect()
        try:
            rows = con.execute(
                """
                SELECT * FROM mgfs_pipeline_results
                WHERE batch_id = ?
                ORDER BY final_score DESC
                """,
                [batch_id],
            ).fetchall()
            columns = [desc[0] for desc in con.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            con.close()


def _extract_factor_score(decision: InvestmentDecision, key: str) -> float | None:
    score = decision.factor_scores.get(key)
    return score.score if score else None

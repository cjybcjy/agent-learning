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


def _extract_factor_score(decision: InvestmentDecision, key: str) -> float | None:
    score = decision.factor_scores.get(key)
    return score.score if score else None

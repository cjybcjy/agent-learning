from __future__ import annotations

from sentinel.domain.models import HeatSnapshot, Market
from sentinel.storage.db import Database


class HeatMetricRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def bootstrap(self) -> None:
        self.database.bootstrap()

    def get_previous_heats(self, market: Market) -> dict[str, float]:
        """Return the most recent directed_heat per symbol for a given market.

        Used to compute period-over-period Δ%.
        """
        con = self.database.connect()
        try:
            rows = con.execute(
                """
                SELECT symbol, directed_heat
                FROM heat_metrics
                WHERE market = ?
                  AND timestamp = (
                      SELECT MAX(timestamp) FROM heat_metrics WHERE market = ?
                  )
                """,
                [market.value, market.value],
            ).fetchall()
        finally:
            con.close()
        return {row[0]: float(row[1]) for row in rows}

    def upsert_snapshots(self, snapshots: list[HeatSnapshot]) -> None:
        if not snapshots:
            return

        rows = [snapshot.to_row() for snapshot in snapshots]
        con = self.database.connect()
        try:
            con.executemany(
                """
                INSERT OR REPLACE INTO heat_metrics (
                    timestamp, market, symbol, base_heat, kol_multiplier,
                    sentiment_score, directed_heat, change_pct, top_source,
                    rank_bullish, rank_bearish, is_anomaly
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["timestamp"],
                        row["market"],
                        row["symbol"],
                        row["base_heat"],
                        row["kol_multiplier"],
                        row["sentiment_score"],
                        row["directed_heat"],
                        row["change_pct"],
                        row["top_source"],
                        row["rank_bullish"],
                        row["rank_bearish"],
                        row["is_anomaly"],
                    )
                    for row in rows
                ],
            )
        finally:
            con.close()

    def list_by_market(self, market: Market) -> list[HeatSnapshot]:
        con = self.database.connect()
        try:
            result = con.execute(
                """
                SELECT timestamp, market, symbol, base_heat, kol_multiplier,
                       sentiment_score, directed_heat, change_pct, top_source,
                       rank_bullish, rank_bearish, is_anomaly
                FROM heat_metrics
                WHERE market = ?
                ORDER BY timestamp DESC, symbol ASC
                """,
                [market.value],
            ).fetchall()
        finally:
            con.close()

        return [
            HeatSnapshot(
                timestamp=row[0],
                market=Market(row[1]),
                symbol=row[2],
                base_heat=row[3],
                kol_multiplier=row[4],
                sentiment_score=row[5],
                directed_heat=row[6],
                change_pct=row[7],
                top_source=row[8],
                rank_bullish=row[9],
                rank_bearish=row[10],
                is_anomaly=row[11],
            )
            for row in result
        ]

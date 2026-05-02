from heatmap.store.dao import Store


class RollupEngine:
    def __init__(self, store: Store):
        self.store = store

    async def compute_rollup_30min(self, window_start: str, window_end: str) -> None:
        """Aggregate mentions for a 30min window"""
        cur = await self.store._db.execute(
            "SELECT m.symbol, COUNT(*) as cnt, COUNT(DISTINCT r.channel) as src_cnt "
            "FROM mentions m JOIN raw_messages r ON r.id = m.message_id "
            "WHERE r.posted_at >= ? AND r.posted_at < ? "
            "GROUP BY m.symbol",
            (window_start, window_end)
        )
        rows = await cur.fetchall()
        for symbol, cnt, src_cnt in rows:
            await self.store.insert_rollup_30min(
                symbol=symbol, window_start=window_start, market="crypto",
                mention_count=cnt, weighted_score=float(cnt), source_count=src_cnt
            )

    async def compute_rollup_4h(self, window_start: str) -> None:
        """Sum 8 consecutive 30min rollups into 4h"""
        end = self._add_hours(window_start, 4)
        cur = await self.store._db.execute(
            "SELECT symbol, SUM(mention_count), SUM(weighted_score), SUM(source_count), market "
            "FROM rollup_30min WHERE window_start >= ? AND window_start < ? GROUP BY symbol",
            (window_start, end)
        )
        rows = await cur.fetchall()
        for symbol, cnt, w_score, src_cnt, market in rows:
            await self.store._db.execute(
                "INSERT INTO rollup_4h(symbol,window_start,market,mention_count,weighted_score,source_count)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT(symbol,window_start) DO UPDATE SET"
                " mention_count=excluded.mention_count, weighted_score=excluded.weighted_score",
                (symbol, window_start, market, cnt, w_score, src_cnt)
            )
        await self.store._db.commit()

    async def compute_rollup_daily(self, date: str) -> None:
        """Sum 6 rollup_4h records into daily (O(1))"""
        start = f"{date}T00:00:00Z"
        end = f"{date}T23:59:59Z"
        cur = await self.store._db.execute(
            "SELECT symbol, SUM(mention_count), SUM(weighted_score), SUM(source_count), market "
            "FROM rollup_4h WHERE window_start >= ? AND window_start <= ? GROUP BY symbol",
            (start, end)
        )
        rows = await cur.fetchall()
        for symbol, cnt, w_score, src_cnt, market in rows:
            await self.store._db.execute(
                "INSERT INTO rollup_daily(symbol,date,market,mention_count,weighted_score,source_count)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT(symbol,date) DO UPDATE SET"
                " mention_count=excluded.mention_count, weighted_score=excluded.weighted_score",
                (symbol, date, market, cnt, w_score, src_cnt)
            )
        await self.store._db.commit()

    @staticmethod
    def _add_hours(iso: str, hours: int) -> str:
        from datetime import datetime, timedelta, timezone
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (dt + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

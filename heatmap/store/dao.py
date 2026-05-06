from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import asyncio
import aiosqlite

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

@dataclass
class RawMessage:
    platform: str
    channel: str
    author_id: str | None
    content: str
    posted_at: datetime
    fetched_at: datetime
    id: int | None = None

@dataclass
class Mention:
    message_id: int
    symbol: str
    matched_alias: str
    is_ambiguous: bool
    confidence: float

@dataclass
class QueuedMessage:
    """Queue element: RawMessage + pre-extracted mentions for batch write."""
    raw: RawMessage
    mentions: list[Mention] | None = None

class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        # aiosqlite 单连接：多个 collector 协程并发写时必须串行化，否则 cursor/lastrowid 会错乱。
        self._write_lock = asyncio.Lock()

    async def init(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def insert_message(self, m: RawMessage) -> int:
        async with self._write_lock:
            cur = await self._db.execute(
                "INSERT INTO raw_messages(platform,channel,author_id,content,posted_at,fetched_at)"
                " VALUES (?,?,?,?,?,?)",
                (m.platform, m.channel, m.author_id, m.content,
                 m.posted_at.isoformat(), m.fetched_at.isoformat()),
            )
            await self._db.commit()
            return cur.lastrowid

    async def insert_message_with_mentions(self, m: RawMessage, mentions: list[Mention]) -> int:
        async with self._write_lock:
            cur = await self._db.execute(
                "INSERT INTO raw_messages(platform,channel,author_id,content,posted_at,fetched_at)"
                " VALUES (?,?,?,?,?,?)",
                (m.platform, m.channel, m.author_id, m.content,
                 m.posted_at.isoformat(), m.fetched_at.isoformat()),
            )
            mid = cur.lastrowid
            if mentions:
                await self._db.executemany(
                    "INSERT INTO mentions(message_id,symbol,matched_alias,is_ambiguous,confidence)"
                    " VALUES (?,?,?,?,?)",
                    [(mid, x.symbol, x.matched_alias, int(x.is_ambiguous), x.confidence)
                     for x in mentions],
                )
            await self._db.commit()
            return mid

    async def insert_mentions(self, mentions: list[Mention]) -> None:
        async with self._write_lock:
            await self._db.executemany(
                "INSERT INTO mentions(message_id,symbol,matched_alias,is_ambiguous,confidence)"
                " VALUES (?,?,?,?,?)",
                [(x.message_id, x.symbol, x.matched_alias, int(x.is_ambiguous), x.confidence)
                 for x in mentions],
            )
            await self._db.commit()

    async def daily_mention_counts(self, date: str) -> dict[str, int]:
        cur = await self._db.execute(
            "SELECT m.symbol, COUNT(*) FROM mentions m "
            "JOIN raw_messages r ON r.id = m.message_id "
            "WHERE substr(r.posted_at,1,10) = ? GROUP BY m.symbol",
            (date,),
        )
        rows = await cur.fetchall()
        return {row[0]: row[1] for row in rows}

    async def upsert_daily_score(self, symbol: str, date: str,
                                 mention_count: int, weighted_score: float,
                                 alpha: float | None, beta: float | None,
                                 composite: float | None) -> None:
        async with self._write_lock:
            await self._db.execute(
                "INSERT INTO daily_scores(symbol,date,mention_count,weighted_score,alpha,beta,composite)"
                " VALUES (?,?,?,?,?,?,?) "
                " ON CONFLICT(symbol,date) DO UPDATE SET "
                "  mention_count=excluded.mention_count,"
                "  weighted_score=excluded.weighted_score,"
                "  alpha=excluded.alpha, beta=excluded.beta, composite=excluded.composite",
                (symbol, date, mention_count, weighted_score, alpha, beta, composite),
            )
            await self._db.commit()

    async def get_weighted_score(self, symbol: str, date: str) -> float | None:
        cur = await self._db.execute(
            "SELECT weighted_score FROM daily_scores WHERE symbol=? AND date=?",
            (symbol, date),
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def insert_rollup_30min(
        self, symbol: str, window_start: str, market: str,
        mention_count: int, weighted_score: float, source_count: int
    ) -> None:
        async with self._write_lock:
            await self._db.execute(
                "INSERT OR REPLACE INTO rollup_30min"
                "(symbol,window_start,market,mention_count,weighted_score,source_count)"
                " VALUES (?,?,?,?,?,?)",
                (symbol, window_start, market, mention_count, weighted_score, source_count),
            )
            await self._db.commit()

    async def get_rollup_30min(self, symbol: str, window_start: str) -> list[dict]:
        cur = await self._db.execute(
            "SELECT * FROM rollup_30min WHERE symbol=? AND window_start=?",
            (symbol, window_start),
        )
        rows = await cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in rows]

    async def insert_ai_call_log(
        self, symbol: str, window_start: str, model_version: str,
        called_at: str, cost_estimate: float | None = None
    ) -> None:
        async with self._write_lock:
            await self._db.execute(
                "INSERT INTO ai_call_log(symbol,window_start,model_version,called_at,cost_estimate)"
                " VALUES (?,?,?,?,?)",
                (symbol, window_start, model_version, called_at, cost_estimate),
            )
            await self._db.commit()

    async def get_ai_call_count_today(self, date: str) -> int:
        cur = await self._db.execute(
            "SELECT COUNT(*) FROM ai_call_log WHERE substr(called_at,1,10) = ?",
            (date,),
        )
        row = await cur.fetchone()
        return row[0] if row else 0

    async def get_rollup_heatmap(
        self, granularity: str, market: str, limit: int, cursor: str | None
    ) -> tuple[list[dict], str | None]:
        table = {"30min": "rollup_30min", "4h": "rollup_4h", "day": "rollup_daily"}.get(granularity, "rollup_30min")
        time_col = "window_start" if granularity != "day" else "date"
        params: list = []
        where_clauses = []
        if market != "all":
            where_clauses.append("market = ?")
            params.append(market)
        if cursor:
            # cursor format: "window_start|symbol"
            parts = cursor.split("|")
            if len(parts) == 2:
                where_clauses.append(f"({time_col} < ? OR ({time_col} = ? AND symbol > ?))")
                params.extend([parts[0], parts[0], parts[1]])
        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        order_col = time_col
        sql = f"SELECT symbol, {time_col} as window_start, market, mention_count, weighted_score, source_count FROM {table} {where_sql} ORDER BY {order_col} DESC, symbol ASC LIMIT ?"
        params.append(limit + 1)
        cur = await self._db.execute(sql, tuple(params))
        rows = await cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        items = [dict(zip(cols, row)) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit]
            next_cursor = f"{last[1]}|{last[0]}"
        return items, next_cursor

    async def get_rollup_trend(self, symbol: str, granularity: str, days: int = 7) -> list[dict]:
        table = {"30min": "rollup_30min", "4h": "rollup_4h", "day": "rollup_daily"}.get(granularity, "rollup_30min")
        time_col = "window_start" if granularity != "day" else "date"
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cur = await self._db.execute(
            f"SELECT symbol, {time_col} as window_start, mention_count, weighted_score, source_count FROM {table} WHERE symbol = ? AND {time_col} >= ? ORDER BY {time_col} ASC",
            (symbol, since),
        )
        rows = await cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in rows]

    async def get_ai_signals_for_symbol(self, symbol: str, limit: int = 10) -> list[dict]:
        cur = await self._db.execute(
            "SELECT * FROM ai_signals WHERE symbol = ? ORDER BY created_at DESC LIMIT ?",
            (symbol, limit),
        )
        rows = await cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in rows]

    async def get_symbols_by_market(self, market: str) -> list[str]:
        if market == "all":
            cur = await self._db.execute("SELECT DISTINCT symbol FROM rollup_30min")
        else:
            cur = await self._db.execute(
                "SELECT DISTINCT symbol FROM rollup_30min WHERE market = ?",
                (market,),
            )
        rows = await cur.fetchall()
        return [row[0] for row in rows]

    async def get_top_posts(self, symbol: str, window_start: str, window_end: str, limit: int = 10) -> list[dict]:
        cur = await self._db.execute(
            "SELECT r.content, r.platform, r.channel, r.posted_at, r.author_id "
            "FROM raw_messages r JOIN mentions m ON m.message_id = r.id "
            "WHERE m.symbol = ? AND r.posted_at >= ? AND r.posted_at < ? "
            "ORDER BY length(r.content) DESC LIMIT ?",
            (symbol, window_start, window_end, limit),
        )
        rows = await cur.fetchall()
        return [
            {
                "content": row[0],
                "platform": row[1],
                "channel": row[2],
                "posted_at": row[3],
                "author_id": row[4],
                "interactions": 0,
            }
            for row in rows
        ]

    async def get_rollup_30min_history(self, symbol: str, since: str) -> list[tuple[str, int]]:
        cur = await self._db.execute(
            "SELECT window_start, mention_count FROM rollup_30min WHERE symbol = ? AND window_start >= ? ORDER BY window_start ASC",
            (symbol, since),
        )
        rows = await cur.fetchall()
        return rows

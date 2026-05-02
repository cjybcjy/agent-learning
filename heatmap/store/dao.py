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

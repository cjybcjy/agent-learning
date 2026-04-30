from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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

    async def init(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def insert_message(self, m: RawMessage) -> int:
        cur = await self._db.execute(
            "INSERT INTO raw_messages(platform,channel,author_id,content,posted_at,fetched_at)"
            " VALUES (?,?,?,?,?,?)",
            (m.platform, m.channel, m.author_id, m.content,
             m.posted_at.isoformat(), m.fetched_at.isoformat()),
        )
        await self._db.commit()
        return cur.lastrowid

    async def insert_mentions(self, mentions: list[Mention]) -> None:
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

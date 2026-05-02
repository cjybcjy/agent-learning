import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from heatmap.store.dao import Store, RawMessage


class BatchWriter:
    def __init__(self, batch_size: int = 100, dlq_dir: Path | None = None):
        self.batch_size = batch_size
        self.dlq_dir = dlq_dir
        if dlq_dir:
            dlq_dir.mkdir(parents=True, exist_ok=True)

    async def run(self, queue: asyncio.Queue, store: Store):
        """Main loop: consume from queue, batch write to store."""
        batch = []
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                batch.append(msg)
                if len(batch) >= self.batch_size:
                    await self._flush(store, batch)
                    batch = []
            except asyncio.TimeoutError:
                if batch:
                    await self._flush(store, batch)
                    batch = []
            except asyncio.CancelledError:
                if batch:
                    await self._flush(store, batch)
                raise

    async def _flush(self, store: Store, batch: list[RawMessage]):
        try:
            for msg in batch:
                await store.insert_message(msg)
        except Exception:
            if self.dlq_dir:
                self._write_dlq(batch)

    def _write_dlq(self, batch: list[RawMessage]):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        path = self.dlq_dir / f"dlq_{ts}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            for msg in batch:
                f.write(json.dumps({
                    "platform": msg.platform,
                    "channel": msg.channel,
                    "author_id": msg.author_id,
                    "content": msg.content,
                    "posted_at": msg.posted_at.isoformat(),
                    "fetched_at": msg.fetched_at.isoformat(),
                }, ensure_ascii=False) + "\n")

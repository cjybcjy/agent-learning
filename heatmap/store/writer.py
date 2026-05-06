import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from heatmap.store.dao import Store, RawMessage, QueuedMessage

LOG = logging.getLogger("heatmap.writer")


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

    async def _flush(self, store: Store, batch: list):
        try:
            for item in batch:
                if isinstance(item, QueuedMessage):
                    await store.insert_message_with_mentions(item.raw, item.mentions or [])
                else:
                    # Backward compat: raw RawMessage without mentions
                    await store.insert_message(item)
        except Exception:
            LOG.exception("Batch flush failed, writing %d messages to DLQ", len(batch))
            if self.dlq_dir:
                await self._write_dlq(batch)

    async def _write_dlq(self, batch: list):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        uid = uuid.uuid4().hex[:8]
        path = self.dlq_dir / f"dlq_{ts}_{uid}.jsonl"

        lines = []
        for item in batch:
            msg = item.raw if isinstance(item, QueuedMessage) else item
            lines.append(json.dumps({
                "platform": msg.platform,
                "channel": msg.channel,
                "author_id": msg.author_id,
                "content": msg.content,
                "posted_at": msg.posted_at.isoformat(),
                "fetched_at": msg.fetched_at.isoformat(),
            }, ensure_ascii=False))

        content = "\n".join(lines) + "\n"

        def _sync_write():
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

        await asyncio.to_thread(_sync_write)

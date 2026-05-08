import asyncio
import logging
import os
from datetime import datetime, timezone

from telethon import TelegramClient, events

from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.store.dao import Mention, RawMessage, QueuedMessage

LOG = logging.getLogger("heatmap.collectors.telegram")


class TelegramCollector:
    def __init__(
        self,
        extractor: AhoCorasickExtractor,
        channels: list[str],
        queue: asyncio.Queue,
        market: str = "crypto",
    ):
        self.extractor = extractor
        self.channels = channels
        self.queue = queue
        self.market = market
        api_id = int(os.environ["TELEGRAM_API_ID"])
        api_hash = os.environ["TELEGRAM_API_HASH"]
        session = os.environ.get("TELEGRAM_SESSION", "heatmap_session")
        self.client = TelegramClient(session, api_id, api_hash)

    async def run(self) -> None:
        await self.client.start()

        @self.client.on(events.NewMessage(chats=self.channels))
        async def handler(event):
            now = datetime.now(timezone.utc)
            content = event.raw_text or ""
            msg = RawMessage(
                platform="telegram",
                channel=str(event.chat_id),
                author_id=str(event.sender_id) if event.sender_id else None,
                content=content,
                posted_at=event.date.astimezone(timezone.utc) if event.date else now,
                fetched_at=now,
                market=self.market,
            )
            hits = self.extractor.extract(content)
            mentions = [
                Mention(0, h.symbol, h.matched_alias, h.is_ambiguous, 1.0)
                for h in hits
            ]
            try:
                self.queue.put_nowait(QueuedMessage(msg, mentions))
            except asyncio.QueueFull:
                LOG.warning("Queue full, dropping telegram message from %s", msg.channel)

        await self.client.run_until_disconnected()

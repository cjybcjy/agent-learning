import os
from datetime import datetime, timezone

from telethon import TelegramClient, events

from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.store.dao import Mention, RawMessage, Store


class TelegramCollector:
    def __init__(self, store: Store, extractor: AhoCorasickExtractor, channels: list[str]):
        self.store = store
        self.extractor = extractor
        self.channels = channels
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
            mid = await self.store.insert_message(RawMessage(
                platform="telegram",
                channel=str(event.chat_id),
                author_id=str(event.sender_id) if event.sender_id else None,
                content=content,
                posted_at=event.date.astimezone(timezone.utc) if event.date else now,
                fetched_at=now,
            ))
            hits = self.extractor.extract(content)
            if hits:
                await self.store.insert_mentions([
                    Mention(mid, h.symbol, h.matched_alias, h.is_ambiguous, 1.0)
                    for h in hits
                ])

        await self.client.run_until_disconnected()

import os
from datetime import datetime, timezone

import discord

from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.store.dao import Mention, RawMessage, Store


class DiscordCollector:
    def __init__(self, store: Store, extractor: AhoCorasickExtractor,
                 watch_channel_ids: set[int]):
        self.store = store
        self.extractor = extractor
        self.watch = watch_channel_ids
        intents = discord.Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)
        self.client.event(self.on_message)

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id not in self.watch:
            return
        now = datetime.now(timezone.utc)
        mid = await self.store.insert_message(RawMessage(
            platform="discord",
            channel=str(message.channel.id),
            author_id=str(message.author.id),
            content=message.content,
            posted_at=message.created_at.astimezone(timezone.utc),
            fetched_at=now,
        ))
        hits = self.extractor.extract(message.content)
        if hits:
            await self.store.insert_mentions([
                Mention(mid, h.symbol, h.matched_alias, h.is_ambiguous, 1.0)
                for h in hits
            ])

    async def run(self) -> None:
        token = os.environ["DISCORD_BOT_TOKEN"]
        await self.client.start(token)

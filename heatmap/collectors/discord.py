import asyncio
import logging
import os
from datetime import datetime, timezone

import discord

from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.store.dao import Mention, RawMessage, QueuedMessage

LOG = logging.getLogger("heatmap.collectors.discord")


class DiscordCollector:
    def __init__(
        self,
        extractor: AhoCorasickExtractor,
        watch_channel_ids: set[int],
        queue: asyncio.Queue,
        market: str = "crypto",
    ):
        self.extractor = extractor
        self.watch = watch_channel_ids
        self.queue = queue
        self.market = market
        intents = discord.Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)
        self.client.event(self.on_message)

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id not in self.watch:
            return
        now = datetime.now(timezone.utc)
        msg = RawMessage(
            platform="discord",
            channel=str(message.channel.id),
            author_id=str(message.author.id),
            content=message.content,
            posted_at=message.created_at.astimezone(timezone.utc),
            fetched_at=now,
            market=self.market,
        )
        hits = self.extractor.extract(message.content)
        mentions = [
            Mention(0, h.symbol, h.matched_alias, h.is_ambiguous, 1.0)
            for h in hits
        ]
        try:
            self.queue.put_nowait(QueuedMessage(msg, mentions))
        except asyncio.QueueFull:
            LOG.warning("Queue full, dropping discord message from %s", msg.channel)

    async def run(self) -> None:
        token = os.environ["DISCORD_BOT_TOKEN"]
        await self.client.start(token)

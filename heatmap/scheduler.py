import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from heatmap.config import load_thresholds, load_sources
from heatmap.store.dao import Store
from heatmap.extractor.dictionary import load_aliases
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.aggregator.pipeline import run_daily_aggregation
from heatmap.reporter.templates import render_today_table, render_archive_collapsible
from heatmap.reporter.lark_doc import LarkPublisher, LarkCliRunner
from heatmap.collectors.telegram import TelegramCollector
from heatmap.collectors.discord import DiscordCollector

LOG = logging.getLogger("heatmap.scheduler")

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"

async def _daily_loop(store: Store, thresholds, publisher: LarkPublisher):
    while True:
        now = datetime.now(timezone.utc)
        next_run = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        await asyncio.sleep((next_run - now).total_seconds())
        date = (next_run - timedelta(days=1)).date().isoformat()
        try:
            top = await run_daily_aggregation(store, date,
                alpha_min=thresholds.alpha_min, beta_min=thresholds.beta_min,
                stage_a_top_n=thresholds.stage_a_top_n, stage_b_top_n=thresholds.stage_b_top_n)
            today_xml = render_today_table(top, date)
            archive_xml = render_archive_collapsible(top, date)
            await publisher.publish_today(today_xml=today_xml, archive_xml=archive_xml)
            LOG.info("published %s, %d symbols", date, len(top))
        except Exception:
            LOG.exception("daily report failed for %s", date)

async def main():
    logging.basicConfig(level=logging.INFO)
    thresholds = load_thresholds(CONFIG / "thresholds.yaml")
    sources = load_sources(CONFIG / "sources.yaml")
    aliases = load_aliases(CONFIG / "aliases.csv")
    extractor = AhoCorasickExtractor(aliases)

    store = Store(DATA / "heatmap.db"); await store.init()
    publisher = LarkPublisher(state_file=DATA / "state.json", runner=LarkCliRunner())

    tasks = [asyncio.create_task(_daily_loop(store, thresholds, publisher))]

    if sources.telegram.channels:
        tasks.append(asyncio.create_task(
            TelegramCollector(store, extractor, sources.telegram.channels).run()
        ))
    if sources.discord.guilds:
        watch = {int(cid) for g in sources.discord.guilds for cid in g.channel_ids}
        tasks.append(asyncio.create_task(
            DiscordCollector(store, extractor, watch).run()
        ))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())

import argparse
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


async def aggregate_and_publish(store: Store, thresholds, publisher: LarkPublisher,
                                date: str, *, dry_run: bool = False) -> int:
    """跑一次日聚合 + 飞书发布。返回 Top 数量。dry_run=True 时跳过发布。"""
    top = await run_daily_aggregation(
        store, date,
        alpha_min=thresholds.alpha_min, beta_min=thresholds.beta_min,
        stage_a_top_n=thresholds.stage_a_top_n, stage_b_top_n=thresholds.stage_b_top_n,
    )
    today_xml = render_today_table(top, date)
    archive_xml = render_archive_collapsible(top, date)
    LOG.info("aggregated %s, %d symbols qualified", date, len(top))
    if dry_run:
        LOG.info("[dry-run] skipping feishu publish; today_xml preview: %.200s", today_xml)
    else:
        await publisher.publish_today(today_xml=today_xml, archive_xml=archive_xml)
        LOG.info("published %s to feishu", date)
    return len(top)


async def _daily_loop(store: Store, thresholds, publisher: LarkPublisher):
    while True:
        now = datetime.now(timezone.utc)
        next_run = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        wait_s = (next_run - now).total_seconds()
        LOG.info("next daily report at %s UTC (in %.1f h)", next_run.isoformat(), wait_s / 3600)
        await asyncio.sleep(wait_s)
        date = (next_run - timedelta(days=1)).date().isoformat()
        try:
            await aggregate_and_publish(store, thresholds, publisher, date)
        except Exception:
            LOG.exception("daily report failed for %s", date)


async def run_once(date: str | None = None, dry_run: bool = False) -> int:
    """命令行入口：立即跑一次聚合 + 发布并退出。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    thresholds = load_thresholds(CONFIG / "thresholds.yaml")
    target_date = date or datetime.now(timezone.utc).date().isoformat()
    store = Store(DATA / "heatmap.db")
    await store.init()
    try:
        publisher = LarkPublisher(state_file=DATA / "state.json", runner=LarkCliRunner())
        return await aggregate_and_publish(store, thresholds, publisher, target_date, dry_run=dry_run)
    finally:
        await store.close()


async def serve():
    """常驻调度：collectors + 每日 00:05 报告。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    thresholds = load_thresholds(CONFIG / "thresholds.yaml")
    sources = load_sources(CONFIG / "sources.yaml")
    aliases = load_aliases(CONFIG / "aliases.csv")
    extractor = AhoCorasickExtractor(aliases)

    store = Store(DATA / "heatmap.db")
    await store.init()
    publisher = LarkPublisher(state_file=DATA / "state.json", runner=LarkCliRunner())

    tasks = [asyncio.create_task(_daily_loop(store, thresholds, publisher))]

    if sources.telegram.channels:
        LOG.info("starting telegram collector for %d channels", len(sources.telegram.channels))
        tasks.append(asyncio.create_task(
            TelegramCollector(store, extractor, sources.telegram.channels).run()
        ))
    else:
        LOG.warning("config/sources.yaml: telegram.channels is empty — no telegram collector")

    if sources.discord.guilds:
        watch = {int(cid) for g in sources.discord.guilds for cid in g.channel_ids}
        LOG.info("starting discord collector watching %d channel(s)", len(watch))
        tasks.append(asyncio.create_task(
            DiscordCollector(store, extractor, watch).run()
        ))
    else:
        LOG.warning("config/sources.yaml: discord.guilds is empty — no discord collector")

    LOG.info("scheduler ready: %d tasks running. Ctrl+C to stop.", len(tasks))
    await asyncio.gather(*tasks)


def main():
    parser = argparse.ArgumentParser(prog="heatmap.scheduler",
        description="Crypto heatmap scheduler. Default: run as daemon.")
    parser.add_argument("--run-once", action="store_true",
        help="Run one aggregation+publish cycle and exit.")
    parser.add_argument("--date", default=None,
        help="UTC date YYYY-MM-DD for --run-once (default: today UTC).")
    parser.add_argument("--dry-run", action="store_true",
        help="With --run-once: aggregate only, do NOT call lark-cli.")
    args = parser.parse_args()

    if args.run_once:
        n = asyncio.run(run_once(date=args.date, dry_run=args.dry_run))
        print(f"done: {n} symbols qualified")
    else:
        asyncio.run(serve())


if __name__ == "__main__":
    main()

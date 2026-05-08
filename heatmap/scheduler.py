import argparse
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from heatmap.config import load_thresholds, load_sources
from heatmap.store.dao import Store
from heatmap.extractor.dictionary import load_aliases
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.aggregator.rollup import RollupEngine
from heatmap.ai.cost_guard import CostGuard
from heatmap.ai.signal_engine import SignalEngine
from heatmap.collectors.telegram import TelegramCollector
from heatmap.collectors.discord import DiscordCollector
from heatmap.collectors.xueqiu import XueqiuCollector
from heatmap.collectors.rate_limiter import RateLimiter
from heatmap.collectors.proxy_pool import ProxyPool
from heatmap.store.writer import BatchWriter
from heatmap.web.websocket import ws_manager

LOG = logging.getLogger("heatmap.scheduler")

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"


def _next_30min_boundary(now: datetime) -> datetime:
    """Round up to next 30-minute boundary."""
    minute = (now.minute // 30 + 1) * 30
    boundary = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minute)
    return boundary


class RollupScheduler:
    def __init__(self, store: Store, engine: RollupEngine, completion_queue: asyncio.Queue):
        self.store = store
        self.engine = engine
        self.completion_queue = completion_queue

    async def run(self):
        while True:
            now = datetime.now(timezone.utc)
            next_boundary = _next_30min_boundary(now)
            wait_s = (next_boundary - now).total_seconds()
            LOG.info("next rollup at %s UTC (in %.1f min)", next_boundary.isoformat(), wait_s / 60)
            await asyncio.sleep(wait_s)

            window_end = next_boundary
            window_start = window_end - timedelta(minutes=30)
            ws_iso = window_start.isoformat().replace("+00:00", "Z")
            we_iso = window_end.isoformat().replace("+00:00", "Z")

            LOG.info("computing rollup_30min for %s to %s", ws_iso, we_iso)
            try:
                await self.engine.compute_rollup_30min(ws_iso, we_iso)
                await self.completion_queue.put(ws_iso)
            except Exception:
                LOG.exception("rollup_30min failed for %s", ws_iso)
                continue

            # 4h boundary check
            if window_end.hour % 4 == 0 and window_end.minute == 0:
                h4_start = (window_end - timedelta(hours=4)).isoformat().replace("+00:00", "Z")
                LOG.info("computing rollup_4h for %s", h4_start)
                try:
                    await self.engine.compute_rollup_4h(h4_start)
                except Exception:
                    LOG.exception("rollup_4h failed for %s", h4_start)

            # Daily boundary check
            if window_end.hour == 0 and window_end.minute == 0:
                date = (window_end - timedelta(days=1)).date().isoformat()
                LOG.info("computing rollup_daily for %s", date)
                try:
                    await self.engine.compute_rollup_daily(date)
                except Exception:
                    LOG.exception("rollup_daily failed for %s", date)


class AIScheduler:
    def __init__(self, store: Store, signal_engine: SignalEngine, completion_queue: asyncio.Queue):
        self.store = store
        self.signal_engine = signal_engine
        self.completion_queue = completion_queue

    async def run(self):
        while True:
            window_start = await self.completion_queue.get()
            LOG.info("AI scheduler checking window %s", window_start)
            try:
                cur = await self.store._db.execute(
                    "SELECT DISTINCT symbol, market FROM rollup_30min WHERE window_start = ?",
                    (window_start,),
                )
                rows = await cur.fetchall()
                for symbol, market in rows:
                    try:
                        result = await self.signal_engine.check_and_trigger(symbol, window_start, market)
                        if result:
                            LOG.info("AI signal triggered for %s: anomaly=%s", symbol, result.get("anomaly_score"))
                    except Exception:
                        LOG.exception("AI check failed for %s @ %s", symbol, window_start)
            except Exception:
                LOG.exception("AI scheduler failed for window %s", window_start)


async def _batch_writer_loop(queue: asyncio.Queue, store: Store):
    """Run BatchWriter for future collectors that use Queue."""
    writer = BatchWriter(batch_size=100, dlq_dir=DATA / "dlq")
    await writer.run(queue, store)


async def serve():
    """常驻调度：collectors + rollup + AI + batch writer."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    thresholds = load_thresholds(CONFIG / "thresholds.yaml")
    sources = load_sources(CONFIG / "sources.yaml")
    aliases = load_aliases(CONFIG / "aliases.csv")
    extractor = AhoCorasickExtractor(aliases)

    store = Store(DATA / "heatmap.db")
    await store.init()

    queue = asyncio.Queue(maxsize=10000)
    rollup_completion = asyncio.Queue()

    engine = RollupEngine(store)
    cost_guard = CostGuard(store, max_calls_per_day=thresholds.ai.max_calls_per_day)
    signal_engine = SignalEngine(store, cost_guard, thresholds.ai, ws_manager)

    tasks = [
        asyncio.create_task(_batch_writer_loop(queue, store)),
        asyncio.create_task(RollupScheduler(store, engine, rollup_completion).run()),
        asyncio.create_task(AIScheduler(store, signal_engine, rollup_completion).run()),
    ]

    # All collectors use Queue + BatchWriter architecture
    limiter = RateLimiter(thresholds.rate_limits)
    proxy_pool = ProxyPool(thresholds.proxies)

    if sources.telegram.channels:
        LOG.info("starting telegram collector for %d channels", len(sources.telegram.channels))
        tasks.append(asyncio.create_task(
            TelegramCollector(extractor, sources.telegram.channels, queue, market="crypto").run()
        ))
    else:
        LOG.warning("config/sources.yaml: telegram.channels is empty")

    if sources.discord.guilds:
        watch = {int(cid) for g in sources.discord.guilds for cid in g.channel_ids}
        LOG.info("starting discord collector watching %d channel(s)", len(watch))
        tasks.append(asyncio.create_task(
            DiscordCollector(extractor, watch, queue, market="crypto").run()
        ))
    else:
        LOG.warning("config/sources.yaml: discord.guilds is empty")

    LOG.info("starting xueqiu collector")
    xq = XueqiuCollector(extractor, queue, market="a_share", limiter=limiter, proxy_pool=proxy_pool)
    tasks.append(asyncio.create_task(xq.run()))

    LOG.info("scheduler ready: %d tasks running. Ctrl+C to stop.", len(tasks))
    try:
        await asyncio.gather(*tasks)
    finally:
        await signal_engine.close()
        await store.close()


def main():
    parser = argparse.ArgumentParser(prog="heatmap.scheduler",
        description="Market heatmap scheduler.")
    args = parser.parse_args()
    asyncio.run(serve())


if __name__ == "__main__":
    main()

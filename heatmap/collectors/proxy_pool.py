import asyncio
import logging
from datetime import datetime, timezone, timedelta

LOG = logging.getLogger("heatmap.proxy_pool")


class ProxyPool:
    def __init__(
        self,
        proxies: list[str],
        cooldown_seconds: float = 600.0,
        max_failures: int = 3,
        reaper_interval: float = 30.0,
        health_check_interval: float = 300.0,
    ):
        self._all_proxies = set(proxies)
        self.cooldown_seconds = cooldown_seconds
        self.max_failures = max_failures
        self.reaper_interval = reaper_interval
        self.health_check_interval = health_check_interval
        self._available: set[str] = set(proxies)
        self._cooldown: dict[str, datetime] = {}
        self._failures: dict[str, int] = {}
        self._domain_failures: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None

    async def start(self):
        self._reaper_task = asyncio.create_task(self._reaper())
        self._health_task = asyncio.create_task(self._health_check_loop())

    async def stop(self):
        for task in [self._reaper_task, self._health_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    @property
    def availability_ratio(self) -> float:
        if not self._all_proxies:
            return 1.0
        return len(self._available) / len(self._all_proxies)

    async def get(self, domain: str | None = None) -> str | None:
        async with self._lock:
            if self._available:
                return self._available.pop()
            return None

    async def return_proxy(self, proxy: str):
        """Return a used proxy to the available pool."""
        async with self._lock:
            self._available.add(proxy)

    async def report_failure(self, proxy: str, domain: str | None = None):
        async with self._lock:
            self._failures[proxy] = self._failures.get(proxy, 0) + 1
            if domain:
                self._domain_failures[domain] = self._domain_failures.get(domain, 0) + 1
            if self._failures[proxy] >= self.max_failures:
                cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=self.cooldown_seconds)
                self._cooldown[proxy] = cooldown_until
                self._available.discard(proxy)
                LOG.warning("Proxy %s on cooldown until %s (domain: %s)", proxy, cooldown_until.isoformat(), domain)

    async def _reaper(self):
        while True:
            await asyncio.sleep(self.reaper_interval)
            now = datetime.now(timezone.utc)
            async with self._lock:
                recovered = [p for p, until in self._cooldown.items() if until <= now]
                for p in recovered:
                    del self._cooldown[p]
                    self._failures[p] = 0
                    self._available.add(p)
                if recovered:
                    LOG.info("Reaper: recovered %d proxy(s)", len(recovered))

    async def _health_check_loop(self):
        """Periodically log pool health stats."""
        while True:
            await asyncio.sleep(self.health_check_interval)
            ratio = self.availability_ratio
            LOG.info(
                "Proxy health: %.0f%% available (%d/%d), %d on cooldown",
                ratio * 100, len(self._available), len(self._all_proxies),
                len(self._cooldown),
            )

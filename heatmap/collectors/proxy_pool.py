import asyncio
from datetime import datetime, timezone, timedelta


class ProxyPool:
    def __init__(self, proxies: list[str], cooldown_seconds: float = 600.0, max_failures: int = 3, reaper_interval: float = 30.0):
        self._all_proxies = set(proxies)
        self.cooldown_seconds = cooldown_seconds
        self.max_failures = max_failures
        self.reaper_interval = reaper_interval
        self._available: set[str] = set(proxies)
        self._cooldown: dict[str, datetime] = {}
        self._failures: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None

    async def start(self):
        self._reaper_task = asyncio.create_task(self._reaper())

    async def stop(self):
        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass

    async def get(self) -> str | None:
        async with self._lock:
            if self._available:
                return self._available.pop()
            return None

    async def report_failure(self, proxy: str):
        async with self._lock:
            self._failures[proxy] = self._failures.get(proxy, 0) + 1
            if self._failures[proxy] >= self.max_failures:
                cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=self.cooldown_seconds)
                self._cooldown[proxy] = cooldown_until
                self._available.discard(proxy)

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

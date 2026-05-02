import asyncio
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last_update: float


class RateLimiter:
    def __init__(self, limits: dict[str, float]):
        self.limits = limits
        self.buckets: dict[str, _Bucket] = {}
        self.lock = asyncio.Lock()

    async def acquire(self, domain: str, proxy_ip: str | None = None):
        key = f"{domain}:{proxy_ip}" if proxy_ip else domain
        rate = self.limits.get(domain, 1.0)

        async with self.lock:
            now = time.monotonic()
            bucket = self.buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=rate, last_update=now)
                self.buckets[key] = bucket
            else:
                elapsed = now - bucket.last_update
                bucket.tokens = min(rate, bucket.tokens + elapsed * rate)
                bucket.last_update = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return

        # Wait for token refill
        wait_time = (1.0 - bucket.tokens) / rate
        await asyncio.sleep(wait_time)

        async with self.lock:
            now = time.monotonic()
            elapsed = now - bucket.last_update
            bucket.tokens = min(rate, bucket.tokens + elapsed * rate)
            bucket.last_update = now
            bucket.tokens -= 1.0

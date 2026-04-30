from __future__ import annotations

import aiohttp


class HttpClient:
    async def get_json(self, url: str, params: dict[str, object] | None = None, headers: dict[str, str] | None = None) -> dict[str, object]:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as response:
                response.raise_for_status()
                return await response.json()

from typing import Protocol


class BaseCollector(Protocol):
    async def run(self) -> None: ...

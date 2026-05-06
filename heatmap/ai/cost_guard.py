from heatmap.store.dao import Store


class CostGuard:
    def __init__(self, store: Store, max_calls_per_day: int = 50):
        self.store = store
        self.max_calls = max_calls_per_day

    async def can_call(self, date: str) -> bool:
        count = await self.store.get_ai_call_count_today(date)
        return count < self.max_calls

    async def record_call(self, symbol: str, window_start: str, model_version: str) -> None:
        called_at = window_start
        await self.store.insert_ai_call_log(symbol, window_start, model_version, called_at)

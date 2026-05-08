import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from heatmap.ai.llm_client import LLMClient, PROVIDERS
from heatmap.config import AIConfig
from heatmap.store.dao import Store

if TYPE_CHECKING:
    from heatmap.config_store import ConfigStore

LOG = logging.getLogger("heatmap.ai.chat_engine")


SYSTEM_PROMPT = """你是一名量化市场热度分析助手。请根据用户问题提供简洁、专业的分析回答。

可用数据上下文：
- 热度榜单：标的按提及数和加权分数排名
- 趋势数据：标的历史 30min/4h/日级提及趋势
- AI 信号：标的的异常检测、情绪转变、核心驱动因素

回答规则：
1. 数据驱动，引用具体数字
2. 如果涉及预测，明确说明是推测
3. 保持简洁，控制在 200 字以内
4. 使用中文回答
"""


class ChatEngine:
    def __init__(self, store: Store, config: AIConfig, config_store: "ConfigStore | None" = None):
        self.store = store
        self.config = config
        self.config_store = config_store
        self._llm = self._build_llm_client()

    def _build_llm_client(self) -> LLMClient:
        return LLMClient(
            provider=self.config.provider,
            model=self.config.model,
            config_store=self.config_store,
        )

    def switch_provider(self, provider: str, model: str | None = None) -> None:
        """Switch to a different provider at runtime."""
        self.config = self.config.model_copy_with_provider(provider, model)
        self._llm = LLMClient(
            provider=provider,
            model=self.config.model,
            config_store=self.config_store,
        )
        LOG.info("Switched chat provider to %s (model=%s)", provider, self.config.model)

    async def close(self):
        await self._llm.close()

    async def stream_answer(self, question: str, context: dict):
        """Stream SSE chunks for the chat answer."""
        # Gather relevant data based on context
        data_context = await self._gather_context(context)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": f"【实时数据上下文】\n{data_context}"},
            {"role": "user", "content": question},
        ]

        # Verify API key is available before streaming
        try:
            self._llm._api_key()
        except RuntimeError:
            yield "data: {\"chunk\": \"错误：API Key 未配置。请打开设置面板配置。\"}\n\n"
            yield "data: {\"done\": true}\n\n"
            return

        try:
            async for chunk in self._llm.stream_chat(messages):
                yield f"data: {{'chunk': {json.dumps(chunk)}}}\n\n"
        except Exception:
            LOG.exception("Chat streaming failed")
            yield "data: {'chunk': '（服务暂时不可用）'}\n\n"
        yield "data: {'done': true}\n\n"

    async def _gather_context(self, ctx: dict) -> str:
        """Fetch relevant data from store based on context."""
        parts = []
        symbol = ctx.get("focused_symbol")
        market = ctx.get("market", "all")

        if symbol:
            # Get latest rollup data
            rows = await self.store.get_rollup_trend(symbol, "30min", days=1)
            if rows:
                latest = rows[-1]
                parts.append(f"标的 {symbol} 最近 30min: 提及数={latest.get('mention_count', 0)}, 加权分={latest.get('weighted_score', 0):.1f}")

            # Get AI signals
            signals = await self.store.get_ai_signals_for_symbol(symbol, limit=3)
            if signals:
                s = signals[0]
                parts.append(f"最新 AI 信号: 异常度={s.get('anomaly_score', 0):.2f}, 情绪={s.get('sentiment_shift', 'unknown')}, 驱动={s.get('key_driver', 'unknown')}")

        # Get heatmap top items for market context
        if market:
            items, _ = await self.store.get_rollup_heatmap("30min", market, limit=5, cursor=None)
            if items:
                top = ", ".join(f"{r['symbol']}({r['mention_count']})" for r in items[:3])
                parts.append(f"{market} 市场 Top3: {top}")

        return "\n".join(parts) if parts else "暂无实时数据"

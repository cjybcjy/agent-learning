import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx

from pydantic import ValidationError

from heatmap.aggregator.gates import compute_instant_alpha
from heatmap.ai.cost_guard import CostGuard
from heatmap.ai.llm_client import LLMClient, PROVIDERS
from heatmap.ai.models import AISignalResult
from heatmap.ai.prompts import build_prompt
from heatmap.config import AIConfig
from heatmap.store.dao import Store

if TYPE_CHECKING:
    from heatmap.config_store import ConfigStore

LOG = logging.getLogger("heatmap.ai.signal_engine")


class SignalEngine:
    def __init__(
        self,
        store: Store,
        cost_guard: CostGuard,
        config: AIConfig,
        ws_manager=None,
        config_store: "ConfigStore | None" = None,
    ):
        self.store = store
        self.cost_guard = cost_guard
        self.config = config
        self.ws_manager = ws_manager
        self.config_store = config_store
        self._client = httpx.AsyncClient(timeout=60.0)
        self._llm = self._build_llm_client()

    def _build_llm_client(self) -> LLMClient:
        """Build LLMClient from current config. API key resolved lazily at request time."""
        return LLMClient(
            provider=self.config.provider,
            model=self.config.model,
            config_store=self.config_store,
        )

    def _resolve_api_key(self, env_var: str) -> str | None:
        """Look up API key: explicit env var > config_store > generic fallback."""
        key = os.environ.get(env_var)
        if not key and self.config_store:
            key = self.config_store.get(env_var)
        return key

    def switch_provider(self, provider: str, model: str | None = None) -> None:
        """Switch to a different provider at runtime."""
        spec = PROVIDERS.get(provider, PROVIDERS["deepseek"])
        self.config = self.config.model_copy_with_provider(provider, model)
        api_key = self._resolve_api_key(spec.api_key_env)
        self._llm = LLMClient(provider=provider, model=self.config.model, api_key=api_key)
        LOG.info("Switched AI provider to %s (model=%s)", provider, self.config.model)

    async def close(self):
        await self._llm.close()
        await self._client.aclose()

    async def check_and_trigger(
        self, symbol: str, window_start: str, market: str
    ) -> dict | None:
        """Check if a symbol triggers AI analysis and run it."""
        # 1. Get current window data
        rows = await self.store.get_rollup_30min(symbol, window_start)
        if not rows:
            return None
        current = rows[0]
        mention_count = current["mention_count"]
        weighted_score = current["weighted_score"]

        # 2. Get historical same-time-slot data for EMA
        historical = await self._get_historical_same_slot(symbol, window_start)
        hist_values = [h[1] for h in historical]

        # 3. Compute instant alpha
        instant_alpha = compute_instant_alpha(float(mention_count), hist_values)

        # 4. Check thresholds
        if instant_alpha < self.config.instant_alpha_threshold:
            return None
        if mention_count < self.config.min_mentions_for_ai:
            return None

        # 5. Check cost guard
        today = window_start[:10]
        if not await self.cost_guard.can_call(today):
            LOG.warning("AI daily budget exhausted (%d calls)", self.config.max_calls_per_day)
            return None

        # 6. Get top posts
        window_end = self._add_minutes(window_start, 30)
        top_posts = await self.store.get_top_posts(symbol, window_start, window_end, limit=10)

        # 7. Build prompt and call LLM
        sources = f"{current['source_count']} channels"
        prompt = build_prompt(symbol, instant_alpha, sources, top_posts)

        # 8. Call LLM via unified client
        raw_response = await self._llm.chat(prompt)
        if raw_response is None:
            LOG.error("LLM call failed for %s @ %s", symbol, window_start)
            return None

        # 9. Parse JSON with retry + Pydantic validation
        parsed = await self._parse_json(raw_response)
        parse_error = parsed is None
        if parse_error:
            # Fallback: construct a minimal result so downstream code is uniform
            parsed = AISignalResult(
                anomaly_score=0.0,
                sentiment_shift="neutral",
                sentiment_confidence=0.0,
                key_driver="[PARSE_ERROR] 无法解析模型输出",
                key_driver_confidence=0.0,
                driver_keywords=[],
                reasoning="",
            )

        # 10. Record call
        await self.cost_guard.record_call(symbol, window_start, self.config.model)

        # 11. Insert into ai_signals
        created_at = datetime.now(timezone.utc).isoformat()
        await self._insert_signal(symbol, window_start, created_at, parsed, raw_response, parse_error)

        # 12. Broadcast via WebSocket
        signal_payload = {
            "type": "ai_signal",
            "symbol": symbol,
            "window_start": window_start,
            "market": market,
            "anomaly_score": parsed.anomaly_score,
            "sentiment_shift": parsed.sentiment_shift,
            "key_driver": parsed.key_driver,
            "driver_keywords": parsed.driver_keywords,
            "instant_alpha": f"{instant_alpha:.0%}",
            "timestamp": created_at,
        }
        if self.ws_manager:
            await self.ws_manager.broadcast(signal_payload, [market])

        return signal_payload

    async def _get_historical_same_slot(
        self, symbol: str, window_start: str
    ) -> list[tuple[str, int]]:
        """Get past 14 days of same time-slot 30min data for EMA."""
        dt = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
        since = (dt - timedelta(days=14)).isoformat().replace("+00:00", "Z")
        # Extract HH:MM from window_start, e.g. "14:00"
        time_slot = window_start[11:16]
        all_history = await self.store.get_rollup_30min_history(symbol, since)
        # Filter same time slot
        return [(ws, cnt) for ws, cnt in all_history if ws[11:16] == time_slot and ws != window_start]

    async def _parse_json(self, raw: str, retries: int = 1) -> AISignalResult | None:
        """Extract JSON from markdown fences, parse, and validate with Pydantic."""
        for attempt in range(retries + 1):
            try:
                text = raw.strip()
                if text.startswith("```"):
                    lines = text.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()
                data = json.loads(text)
                # Pydantic strict validation — catches out-of-range scores,
                # invalid sentiment literals, missing required fields, etc.
                return AISignalResult.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                if isinstance(exc, ValidationError):
                    LOG.warning("LLM output failed Pydantic validation: %s", exc)
                if attempt < retries:
                    LOG.warning("JSON parse failed, retrying...")
                    continue
                LOG.error("JSON parse/validation failed after %d attempts", retries + 1)
                return None
        return None

    async def _insert_signal(
        self, symbol: str, window_start: str, created_at: str,
        parsed: AISignalResult, raw_analysis: str, parse_error: bool = False,
    ) -> None:
        await self.store._db.execute(
            "INSERT INTO ai_signals"
            "(symbol, window_start, model_version, created_at, anomaly_score, sentiment_shift,"
            " sentiment_confidence, key_driver, key_driver_confidence, driver_keywords, raw_analysis)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                symbol,
                window_start,
                self.config.model,
                created_at,
                parsed.anomaly_score,
                parsed.sentiment_shift,
                parsed.sentiment_confidence,
                parsed.key_driver,
                parsed.key_driver_confidence,
                json.dumps(parsed.driver_keywords, ensure_ascii=False),
                raw_analysis if not parse_error else f"[PARSE_ERROR] {raw_analysis}",
            ),
        )
        await self.store._db.commit()

    @staticmethod
    def _add_minutes(iso: str, minutes: int) -> str:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (dt + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from heatmap.aggregator.gates import compute_instant_alpha
from heatmap.ai.cost_guard import CostGuard
from heatmap.ai.prompts import build_prompt
from heatmap.config import AIConfig
from heatmap.store.dao import Store

LOG = logging.getLogger("heatmap.ai.signal_engine")


class SignalEngine:
    def __init__(
        self,
        store: Store,
        cost_guard: CostGuard,
        config: AIConfig,
        ws_manager=None,
    ):
        self.store = store
        self.cost_guard = cost_guard
        self.config = config
        self.ws_manager = ws_manager
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self):
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

        # 8. Call LLM
        raw_response = await self._call_llm(prompt)
        if raw_response is None:
            return None

        # 9. Parse JSON with retry
        parsed = await self._parse_json(raw_response)
        if parsed is None:
            parsed = {"parse_error": True, "raw_analysis": raw_response}

        # 10. Record call
        await self.cost_guard.record_call(symbol, window_start, self.config.model)

        # 11. Insert into ai_signals
        created_at = datetime.now(timezone.utc).isoformat()
        await self._insert_signal(symbol, window_start, created_at, parsed, raw_response)

        # 12. Broadcast via WebSocket
        signal_payload = {
            "type": "ai_signal",
            "symbol": symbol,
            "window_start": window_start,
            "market": market,
            "anomaly_score": parsed.get("anomaly_score"),
            "sentiment_shift": parsed.get("sentiment_shift"),
            "key_driver": parsed.get("key_driver"),
            "driver_keywords": parsed.get("driver_keywords", []),
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

    async def _call_llm(self, prompt: str) -> str | None:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            LOG.error("API key not found in env var %s", self.config.api_key_env)
            return None

        if "claude" in self.config.model.lower():
            return await self._call_claude(prompt, api_key)
        else:
            return await self._call_openai(prompt, api_key)

    async def _call_claude(self, prompt: str, api_key: str) -> str | None:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            resp = await self._client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", [])
            if content:
                return content[0].get("text", "")
            return None
        except Exception:
            LOG.exception("Claude API call failed")
            return None

    async def _call_openai(self, prompt: str, api_key: str) -> str | None:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "max_tokens": 1024,
        }
        try:
            resp = await self._client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return None
        except Exception:
            LOG.exception("OpenAI API call failed")
            return None

    async def _parse_json(self, raw: str, retries: int = 1) -> dict | None:
        for attempt in range(retries + 1):
            try:
                # Try to extract JSON from markdown code blocks
                text = raw.strip()
                if text.startswith("```"):
                    lines = text.splitlines()
                    # Remove first and last fence if present
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()
                return json.loads(text)
            except json.JSONDecodeError:
                if attempt < retries:
                    LOG.warning("JSON parse failed, retrying...")
                    continue
                LOG.error("JSON parse failed after %d attempts", retries + 1)
                return None
        return None

    async def _insert_signal(
        self, symbol: str, window_start: str, created_at: str,
        parsed: dict, raw_analysis: str
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
                parsed.get("anomaly_score"),
                parsed.get("sentiment_shift"),
                parsed.get("sentiment_confidence"),
                parsed.get("key_driver"),
                parsed.get("key_driver_confidence"),
                json.dumps(parsed.get("driver_keywords", []), ensure_ascii=False),
                raw_analysis if not parsed.get("parse_error") else f"[PARSE_ERROR] {raw_analysis}",
            ),
        )
        await self.store._db.commit()

    @staticmethod
    def _add_minutes(iso: str, minutes: int) -> str:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (dt + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")

import json
import logging
from dataclasses import dataclass

import httpx

LOG = logging.getLogger("heatmap.ai.llm")


@dataclass(frozen=True)
class ProviderSpec:
    """Static metadata for an LLM provider."""

    name: str
    display_name: str
    base_url: str
    api_key_env: str
    default_model: str
    # "openai" = /chat/completions  (DeepSeek, Kimi, Bailian, OpenAI)
    # "anthropic" = /messages       (Claude)
    protocol: str


# ── Provider registry ──
# All Chinese LLMs below use the OpenAI-compatible /chat/completions endpoint,
# so they share the same request/response format. Only Claude needs special handling.

PROVIDERS: dict[str, ProviderSpec] = {
    "deepseek": ProviderSpec(
        name="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-chat",
        protocol="openai",
    ),
    "kimi": ProviderSpec(
        name="kimi",
        display_name="Kimi (Moonshot)",
        base_url="https://api.moonshot.cn/v1",
        api_key_env="KIMI_API_KEY",
        default_model="moonshot-v1-8k",
        protocol="openai",
    ),
    "bailian": ProviderSpec(
        name="bailian",
        display_name="百炼 (通义千问)",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="BAILIAN_API_KEY",
        default_model="qwen-max",
        protocol="openai",
    ),
    "claude": ProviderSpec(
        name="claude",
        display_name="Claude (Anthropic)",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-sonnet-4-6",
        protocol="anthropic",
    ),
    "openai": ProviderSpec(
        name="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o",
        protocol="openai",
    ),
}


def get_provider_names() -> list[str]:
    return list(PROVIDERS.keys())


def get_provider_models() -> list[dict]:
    """Return provider list with their default models for the frontend."""
    return [
        {
            "provider": p.name,
            "display_name": p.display_name,
            "default_model": p.default_model,
            "api_key_env": p.api_key_env,
        }
        for p in PROVIDERS.values()
    ]


class LLMClient:
    """Unified async LLM client supporting multiple providers.

    API keys are resolved lazily at request time:
    1. Explicitly passed key (highest priority)
    2. Environment variable
    3. ConfigStore (lowest priority)
    """

    def __init__(
        self,
        provider: str = "deepseek",
        model: str | None = None,
        api_key: str | None = None,
        config_store=None,
    ):
        self.provider = PROVIDERS.get(provider, PROVIDERS["deepseek"])
        self.model = model or self.provider.default_model
        self._explicit_key = api_key
        self._config_store = config_store
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self):
        await self._client.aclose()

    def with_key(self, api_key: str | None) -> "LLMClient":
        """Return a new client configured with the given API key."""
        return LLMClient(self.provider.name, self.model, api_key, self._config_store)

    # ── Non-streaming (SignalEngine) ──

    async def chat(self, prompt: str) -> str | None:
        """Send a chat completion request and return full text."""
        if self.provider.protocol == "anthropic":
            return await self._call_anthropic(prompt)
        return await self._call_openai_compatible(prompt)

    # ── Streaming (ChatEngine) ──

    async def stream_chat(self, messages: list[dict]):
        """Stream chat completion and yield text chunks."""
        if self.provider.protocol == "anthropic":
            async for chunk in self._stream_anthropic_messages(messages):
                yield chunk
        else:
            async for chunk in self._stream_openai_messages(messages):
                yield chunk

    # ── Internal: non-streaming ──

    async def _call_openai_compatible(self, prompt: str) -> str | None:
        spec = self.provider
        url = f"{spec.base_url}/chat/completions"
        headers = {
            "authorization": f"Bearer {self._api_key()}",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": 1024,
        }
        if spec.name in ("deepseek", "bailian"):
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = await self._client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return None
        except Exception:
            LOG.exception("%s API call failed", spec.display_name)
            return None

    async def _call_anthropic(self, prompt: str) -> str | None:
        spec = self.provider
        url = f"{spec.base_url}/messages"
        headers = {
            "x-api-key": self._api_key(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
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

    # ── Internal: streaming ──

    async def _stream_openai_messages(self, messages: list[dict]):
        """Stream OpenAI-compatible SSE and yield text chunks."""
        spec = self.provider
        url = f"{spec.base_url}/chat/completions"
        headers = {
            "authorization": f"Bearer {self._api_key()}",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": 1024,
        }
        try:
            async with self._client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                        choices = event.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                yield text
                    except json.JSONDecodeError:
                        continue
        except Exception:
            LOG.exception("%s streaming failed", spec.display_name)

    async def _stream_anthropic_messages(self, messages: list[dict]):
        """Stream Anthropic SSE and yield text chunks."""
        spec = self.provider
        url = f"{spec.base_url}/messages"
        headers = {
            "x-api-key": self._api_key(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": messages,
            "stream": True,
        }
        try:
            async with self._client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                        etype = event.get("type")
                        if etype == "content_block_delta":
                            delta = event.get("delta", {})
                            text = delta.get("text", "")
                            if text:
                                yield text
                        elif etype == "message_stop":
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception:
            LOG.exception("Claude streaming failed")

    def _api_key(self) -> str:
        import os

        if self._explicit_key:
            return self._explicit_key
        # Try environment variable
        key = os.environ.get(self.provider.api_key_env)
        if key:
            return key
        # Try config_store
        if self._config_store:
            key = self._config_store.get(self.provider.api_key_env)
            if key:
                return key
        raise RuntimeError(f"No API key set for provider {self.provider.name} (env: {self.provider.api_key_env})")

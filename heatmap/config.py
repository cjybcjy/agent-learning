from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel


class AIConfig(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    instant_alpha_threshold: float = 2.0
    min_mentions_for_ai: int = 20
    max_calls_per_day: int = 50

    def model_copy_with_provider(self, provider: str, model: str | None = None) -> "AIConfig":
        """Return a copy with the given provider and optional model override."""
        from heatmap.ai.llm_client import PROVIDERS
        spec = PROVIDERS.get(provider, PROVIDERS["deepseek"])
        return AIConfig(
            provider=provider,
            model=model or spec.default_model,
            instant_alpha_threshold=self.instant_alpha_threshold,
            min_mentions_for_ai=self.min_mentions_for_ai,
            max_calls_per_day=self.max_calls_per_day,
        )


class CircuitBreakerConfig(BaseModel):
    sleep_minutes: float = 15.0
    threshold: float = 0.2
    duration_seconds: float = 120.0


class Thresholds(BaseModel):
    stage_a_top_n: int
    stage_b_top_n: int
    alpha_min: float
    beta_min: float
    ai: AIConfig = AIConfig()
    rate_limits: dict[str, float] = {}
    proxies: list[str] = []
    circuit_breaker: CircuitBreakerConfig = CircuitBreakerConfig()
    source_weights: dict[str, float] = {}


class DiscordGuild(BaseModel):
    guild_id: str
    channel_ids: list[str]


class TelegramSources(BaseModel):
    channels: list[str] = []


class DiscordSources(BaseModel):
    guilds: list[DiscordGuild] = []


class Sources(BaseModel):
    telegram: TelegramSources = TelegramSources()
    discord: DiscordSources = DiscordSources()


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_thresholds(path: Path) -> Thresholds:
    return Thresholds(**_load_yaml(path))


def load_sources(path: Path) -> Sources:
    return Sources(**_load_yaml(path))

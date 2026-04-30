from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel

class Thresholds(BaseModel):
    stage_a_top_n: int
    stage_b_top_n: int
    alpha_min: float
    beta_min: float

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

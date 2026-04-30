from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    base_dir: Path = Path(__file__).resolve().parent.parent
    config_dir: Path = Path("config")
    data_dir: Path = Path("data")
    database_name: str = "sentinel.duckdb"

    model_config = SettingsConfigDict(env_prefix="SENTINEL_", extra="ignore")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_config_dir(self) -> Path:
        if self.config_dir.is_absolute():
            return self.config_dir
        return self.base_dir / self.config_dir

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_path(self) -> Path:
        if self.data_dir.is_absolute():
            return self.data_dir / self.database_name
        return self.base_dir / self.data_dir / self.database_name


def load_market_config(path: Path) -> dict[str, dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_weights_config(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def get_market_collectors(config: dict[str, dict[str, object]], market: str) -> list[str]:
    market_section = config.get(market, {})
    collectors = market_section.get("collectors", [])
    if not isinstance(collectors, list):
        return []
    return collectors

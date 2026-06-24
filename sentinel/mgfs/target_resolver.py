from __future__ import annotations

from pathlib import Path

import yaml

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import TargetInfo


class TargetResolver:
    """Resolve canonical MGFS target metadata from moat configuration."""

    def __init__(self, moat_config_path: Path) -> None:
        self.moat_config_path = moat_config_path
        self._companies: dict | None = None

    def resolve(
        self,
        *,
        symbol: str,
        market: Market,
        asset_class: str = "equity",
        name: str | None = None,
        sector: str | None = None,
        theme: str | None = None,
        ecosystem_role: str | None = None,
        tags: list[str] | None = None,
    ) -> TargetInfo:
        cfg = self._load_companies().get(symbol, {})
        if not isinstance(cfg, dict):
            cfg = {}

        return TargetInfo(
            symbol=symbol,
            market=market,
            asset_class=asset_class,
            name=name or cfg.get("name"),
            sector=sector or cfg.get("sector"),
            theme=theme or cfg.get("theme"),
            ecosystem_role=ecosystem_role or cfg.get("ecosystem_role"),
            fund_heavy_holding_count=_coerce_optional_int(
                cfg.get("fund_heavy_holding_count")
            ),
            tags=tags or [],
        )

    def _load_companies(self) -> dict:
        if self._companies is not None:
            return self._companies
        if not self.moat_config_path.exists():
            self._companies = {}
            return self._companies
        data = yaml.safe_load(self.moat_config_path.read_text(encoding="utf-8")) or {}
        companies = data.get("companies", {})
        self._companies = companies if isinstance(companies, dict) else {}
        return self._companies


def load_target_name_map(moat_config_path: Path) -> dict[str, str]:
    """Load canonical stock names keyed by symbol from moat configuration."""
    if not moat_config_path.exists():
        return {}
    data = yaml.safe_load(moat_config_path.read_text(encoding="utf-8")) or {}
    companies = data.get("companies", {})
    if not isinstance(companies, dict):
        return {}

    names: dict[str, str] = {}
    for symbol, cfg in companies.items():
        if not isinstance(cfg, dict):
            continue
        name = cfg.get("name")
        if isinstance(name, str) and name.strip():
            names[str(symbol)] = name.strip()
    return names


def _coerce_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None

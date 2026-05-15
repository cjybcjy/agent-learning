from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "archetypes": {
        "traditional_growth": {
            "label": "传统价值成长",
            "metrics": {"primary": {"name": "PE_TTM", "weight": 0.5}},
            "zones": {"strong_buy": {"percentile_max": 20, "score_range": [90, 100]}},
            "circuit_breakers": {"hard_veto_percentile": 90},
        }
    },
    "sector_to_archetype": {},
    "default_archetype": "traditional_growth",
    "override_archetypes": {},
}


class ArchetypeRouter:
    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path
        self._config: dict[str, Any] | None = None

    def _load_config(self) -> dict[str, Any]:
        if self._config is not None:
            return self._config

        if self._config_path is not None and self._config_path.exists():
            with self._config_path.open("r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
                if loaded is not None:
                    self._config = loaded
                    return self._config

        self._config = DEFAULT_CONFIG.copy()
        return self._config

    def resolve_archetype(self, symbol: str, sector: str | None) -> dict[str, Any]:
        config = self._load_config()
        archetypes = config.get("archetypes", {})
        default_name = config.get("default_archetype", "traditional_growth")

        # Priority 1: override by symbol (check effective_until)
        overrides = config.get("override_archetypes", {})
        override = overrides.get(symbol)
        if override is not None:
            effective_until = override.get("effective_until")
            if effective_until is None:
                # No expiry = permanent override
                archetype_name = override["archetype"]
                return archetypes.get(archetype_name, archetypes.get(default_name, {}))
            else:
                try:
                    expiry = datetime.strptime(effective_until, "%Y-%m-%d")
                    if datetime.now() <= expiry:
                        archetype_name = override["archetype"]
                        return archetypes.get(archetype_name, archetypes.get(default_name, {}))
                except ValueError:
                    pass

        # Priority 2: sector mapping
        if sector is not None:
            sector = sector.strip().replace(" ", "")
            sector_map = config.get("sector_to_archetype", {})
            archetype_name = sector_map.get(sector)
            if archetype_name is not None:
                return archetypes.get(archetype_name, archetypes.get(default_name, {}))

        # Priority 3: default archetype
        return archetypes.get(default_name, {})

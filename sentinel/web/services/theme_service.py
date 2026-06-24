from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sentinel.config import AppSettings

LEGACY_THEME_LABELS = {
    "AI_Compute_Infrastructure": "AI 算力基建",
    "New_Energy_Materials": "新能源材料",
    "Consumer_Staples": "消费复苏与必需消费",
    "Financial_Services": "金融稳定与高股息红利",
    "Advanced_Manufacturing": "设备更新与高端制造",
}


def load_macro_themes(config_path: Path | None = None) -> list[dict[str, str]]:
    path = config_path or AppSettings().resolved_config_dir / "ecosystem_themes.yaml"
    if not path.exists():
        return []

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    catalog = data.get("macro_themes")
    if isinstance(catalog, list):
        themes = [_coerce_theme(item) for item in catalog if isinstance(item, dict)]
        return [theme for theme in themes if theme["key"]]

    hot_themes = data.get("hot_themes", [])
    if not isinstance(hot_themes, list):
        return []
    return [
        {
            "key": str(theme_key),
            "label": LEGACY_THEME_LABELS.get(str(theme_key), str(theme_key)),
            "policy_anchor": "",
        }
        for theme_key in hot_themes
        if str(theme_key).strip()
    ]


def _coerce_theme(item: dict[str, Any]) -> dict[str, str]:
    key = str(item.get("key", "")).strip()
    return {
        "key": key,
        "label": str(item.get("label") or key).strip(),
        "policy_anchor": str(item.get("policy_anchor", "")).strip(),
    }

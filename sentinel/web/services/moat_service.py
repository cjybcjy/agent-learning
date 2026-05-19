from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sentinel.config import AppSettings

settings = AppSettings()

# Default dimension keys for moat radar chart
_MOAT_DIMENSION_KEYS = [
    "brand_premium",
    "franchise_barrier",
    "switching_cost",
    "network_effect",
    "cost_advantage",
]

_MOAT_DIMENSION_LABELS = {
    "brand_premium": "品牌溢价",
    "franchise_barrier": "特许壁垒",
    "switching_cost": "转换成本",
    "network_effect": "网络效应",
    "cost_advantage": "成本优势",
}


def get_moat_dimensions(symbol: str) -> dict[str, Any] | None:
    """Load moat base_score dimensions for a symbol from config.

    Returns dict like:
        {
            "brand_premium": {"score": 95, "note": "..."},
            "franchise_barrier": {"score": 90, "note": "..."},
            ...
        }
    """
    moat_path = settings.resolved_config_dir / "moat_static_base.yaml"
    if not moat_path.exists():
        return None

    data = yaml.safe_load(moat_path.read_text(encoding="utf-8")) or {}
    companies = data.get("companies", {})
    cfg = companies.get(symbol)
    if not cfg:
        return None

    base_score = cfg.get("base_score", {})
    result: dict[str, Any] = {}
    for key in _MOAT_DIMENSION_KEYS:
        item = base_score.get(key)
        if isinstance(item, dict) and "score" in item:
            result[key] = {
                "score": item["score"],
                "label": _MOAT_DIMENSION_LABELS.get(key, key),
                "note": item.get("note", ""),
            }
    return result if result else None


def build_moat_radar_data(symbol: str) -> dict[str, Any] | None:
    """Build data structure for ECharts radar chart.

    Returns:
        {
            "indicator": [{"name": "品牌溢价", "max": 100}, ...],
            "values": [95, 90, 88, 60, 70],
        }
    """
    dims = get_moat_dimensions(symbol)
    if not dims:
        return None

    indicator = []
    values = []
    for key in _MOAT_DIMENSION_KEYS:
        if key in dims:
            indicator.append({"name": dims[key]["label"], "max": 100})
            values.append(dims[key]["score"])

    return {"indicator": indicator, "values": values}

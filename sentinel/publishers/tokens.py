"""Manage lark_docs.yaml — persists Bitable/Doc tokens across runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_lark_docs_config(config_path: Path) -> dict[str, Any]:
    """Load lark_docs.yaml, returning empty dict if file doesn't exist."""
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data or {}


def save_lark_docs_config(config_path: Path, data: dict[str, Any]) -> None:
    """Write lark_docs.yaml."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

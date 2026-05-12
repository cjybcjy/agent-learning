from __future__ import annotations

import importlib
import logging
from pathlib import Path

import yaml

from sentinel.mgfs.factor_plugin import BaseFactorPlugin
from sentinel.mgfs.orchestrator import MGFSOrchestrator

logger = logging.getLogger(__name__)


def load_mgfs_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"MGFS config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_orchestrator(config: dict) -> MGFSOrchestrator:
    modules = config.get("modules", {})
    scoring_formula = config.get("scoring_formula", {})
    policy_multipliers = _extract_policy_multipliers(
        config.get("policy_multiplier", {})
    )
    circuit_breakers = list(config.get("circuit_breakers", {}).values())
    rating_thresholds = list(config.get("rating_thresholds", {}).values())

    plugins: list[BaseFactorPlugin] = []
    for key, module_config in modules.items():
        if not module_config.get("enabled", False):
            continue
        try:
            plugin = _load_plugin(module_config["class_path"])
            plugins.append(plugin)
        except Exception:
            logger.exception("Failed to load plugin %s", key)

    scoring_weights = {
        key: cfg["weight"] for key, cfg in scoring_formula.items()
    }

    return MGFSOrchestrator(
        plugins=plugins,
        scoring_weights=scoring_weights,
        policy_multipliers=policy_multipliers,
        circuit_breakers=circuit_breakers,
        rating_thresholds=rating_thresholds,
    )


def _load_plugin(class_path: str) -> BaseFactorPlugin:
    module_name, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return cls()


def _extract_policy_multipliers(raw: dict) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, cfg in raw.items():
        if isinstance(cfg, dict) and "multiplier" in cfg:
            result[key] = float(cfg["multiplier"])
    return result

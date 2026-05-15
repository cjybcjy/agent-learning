from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path

import yaml

from sentinel.mgfs.factor_plugin import BaseFactorPlugin
from sentinel.mgfs.orchestrator import MGFSOrchestrator

logger = logging.getLogger(__name__)


def load_mgfs_config(path: Path) -> dict:
    """Load and parse an MGFS YAML configuration file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        A dictionary representing the parsed YAML configuration.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"MGFS config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_orchestrator(config: dict, config_dir: Path | None = None) -> MGFSOrchestrator:
    """Build an MGFSOrchestrator instance from a parsed configuration dict.

    Args:
        config: Dictionary loaded by load_mgfs_config containing modules,
            scoring_formula, policy_multiplier, circuit_breakers, and
            rating_thresholds.
        config_dir: Optional directory containing plugin-specific config files.

    Returns:
        An initialized MGFSOrchestrator with loaded plugins and settings.
    """
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
            plugin = _load_plugin(module_config["class_path"], config_dir, key)
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


def _load_plugin(class_path: str, config_dir: Path | None = None, key: str = "") -> BaseFactorPlugin:
    module_name, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    if not inspect.isclass(cls) or not issubclass(cls, BaseFactorPlugin):
        raise TypeError(f"{class_path} is not a BaseFactorPlugin subclass")
    sig = inspect.signature(cls.__init__)
    kwargs: dict[str, object] = {}
    if config_dir is not None and "config_path" in sig.parameters:
        config_file = _plugin_config_file(key)
        if config_file:
            kwargs["config_path"] = config_dir / config_file
    return cls(**kwargs)


def _plugin_config_file(key: str) -> str | None:
    mapping = {
        "moat": "moat_static_base.yaml",
        "policy": "policy_whitelist.yaml",
        "valuation": "valuation_sector_routing.yaml",
    }
    return mapping.get(key)


def _extract_policy_multipliers(raw: dict) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, cfg in raw.items():
        if isinstance(cfg, dict) and "multiplier" in cfg:
            result[key] = float(cfg["multiplier"])
    return result

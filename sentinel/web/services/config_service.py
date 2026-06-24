from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import yaml

from sentinel.config import AppSettings
from sentinel.mgfs.config_validator import validate_mgfs_config

settings = AppSettings()
CONFIG_DIR = settings.resolved_config_dir
SCORE_WEIGHT_FIELDS = {
    "moat": ("moat_weight", "护城河"),
    "valuation": ("valuation_weight", "估值"),
    "policy": ("policy_weight", "政策"),
    "timing": ("timing_weight", "择时"),
}
SCORE_THRESHOLD_FIELDS = {
    "strong_buy": ("strong_buy_min_score", "Strong Buy"),
    "accumulate": ("accumulate_min_score", "Accumulate"),
    "hold_watch": ("hold_watch_min_score", "Hold/Watch"),
}
ALLOWED_FILES = {
    "mgfs_config.yaml",
    "moat_static_base.yaml",
    "valuation_sector_routing.yaml",
    "policy_whitelist.yaml",
    "ecosystem_themes.yaml",
    "research_signal_sources.yaml",
}


def list_allowed_files() -> list[str]:
    return sorted(ALLOWED_FILES)


def load_config(filename: str) -> str:
    if filename not in ALLOWED_FILES:
        raise ValueError(f"不允许编辑的文件: {filename}")
    path = CONFIG_DIR / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_score_composition() -> dict:
    content = load_config("mgfs_config.yaml")
    data = yaml.safe_load(content) if content.strip() else {}
    if not isinstance(data, dict):
        data = {}

    scoring_formula = data.get("scoring_formula", {})
    rating_thresholds = data.get("rating_thresholds", {})
    if not isinstance(scoring_formula, dict):
        scoring_formula = {}
    if not isinstance(rating_thresholds, dict):
        rating_thresholds = {}

    weights = []
    for key, (field_name, label) in SCORE_WEIGHT_FIELDS.items():
        cfg = scoring_formula.get(key, {})
        value = cfg.get("weight", 0.0) if isinstance(cfg, dict) else 0.0
        weights.append(
            {
                "key": key,
                "name": field_name,
                "label": label,
                "value": float(value or 0.0),
            }
        )

    thresholds = []
    for key, (field_name, label) in SCORE_THRESHOLD_FIELDS.items():
        cfg = rating_thresholds.get(key, {})
        value = cfg.get("min_score", 0.0) if isinstance(cfg, dict) else 0.0
        thresholds.append(
            {
                "key": key,
                "name": field_name,
                "label": label,
                "value": float(value or 0.0),
            }
        )

    return {"weights": weights, "thresholds": thresholds}


def validate_config(content: str, filename: str | None = None) -> tuple[bool, list[str]]:
    errors: list[str] = []
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return False, [f"YAML 语法错误: {e}"]

    if data is None:
        return False, ["YAML 内容为空"]

    if filename == "mgfs_config.yaml":
        issues = validate_mgfs_config(data)
        errors.extend(f"{issue.path}: {issue.message}" for issue in issues)
        return len(errors) == 0, errors

    # Moat config validation
    if "companies" in data:
        companies = data.get("companies", {})
        for symbol, cfg in companies.items():
            base_score = cfg.get("base_score", {}) if isinstance(cfg, dict) else {}
            for dim, item in base_score.items():
                if isinstance(item, dict):
                    score = item.get("score")
                    if score is not None and not (0 <= score <= 100):
                        errors.append(f"{symbol}.{dim}.score={score} 超出 [0,100]")

    # Scoring weights sum check
    if "scoring_weights" in data:
        weights = data["scoring_weights"]
        total = sum(w.get("weight", 0) for w in weights.values() if isinstance(w, dict))
        if total > 0 and abs(total - 1.0) > 0.01:
            errors.append(f"scoring_weights 总和={total:.2f}，建议归一化为 1.0")

    return len(errors) == 0, errors


def save_score_composition(
    *,
    moat_weight: float,
    valuation_weight: float,
    policy_weight: float,
    timing_weight: float,
    strong_buy_min_score: float,
    accumulate_min_score: float,
    hold_watch_min_score: float,
) -> tuple[bool, str]:
    weights = {
        "moat": moat_weight,
        "valuation": valuation_weight,
        "policy": policy_weight,
        "timing": timing_weight,
    }
    thresholds = {
        "strong_buy": strong_buy_min_score,
        "accumulate": accumulate_min_score,
        "hold_watch": hold_watch_min_score,
    }

    invalid_weights = [key for key, value in weights.items() if value < 0 or value > 1]
    if invalid_weights:
        return False, f"权重必须在 0..1: {', '.join(invalid_weights)}"

    invalid_thresholds = [
        key for key, value in thresholds.items() if value < 0 or value > 100
    ]
    if invalid_thresholds:
        return False, f"评级阈值必须在 0..100: {', '.join(invalid_thresholds)}"
    if not (strong_buy_min_score >= accumulate_min_score >= hold_watch_min_score):
        return False, "评级阈值需满足 Strong Buy >= Accumulate >= Hold/Watch"

    content = load_config("mgfs_config.yaml")
    data = yaml.safe_load(content) if content.strip() else {}
    if not isinstance(data, dict):
        return False, "mgfs_config.yaml 必须是 mapping"

    scoring_formula = data.setdefault("scoring_formula", {})
    if not isinstance(scoring_formula, dict):
        return False, "scoring_formula 必须是 mapping"
    for key, value in weights.items():
        cfg = scoring_formula.setdefault(key, {})
        if not isinstance(cfg, dict):
            return False, f"scoring_formula.{key} 必须是 mapping"
        cfg["weight"] = float(value)

    rating_thresholds = data.setdefault("rating_thresholds", {})
    if not isinstance(rating_thresholds, dict):
        return False, "rating_thresholds 必须是 mapping"
    for key, value in thresholds.items():
        cfg = rating_thresholds.setdefault(key, {})
        if not isinstance(cfg, dict):
            return False, f"rating_thresholds.{key} 必须是 mapping"
        cfg["min_score"] = float(value)

    content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return save_config("mgfs_config.yaml", content)


def save_config(filename: str, content: str) -> tuple[bool, str]:
    if filename not in ALLOWED_FILES:
        return False, f"不允许编辑的文件: {filename}"

    is_valid, errors = validate_config(content, filename)
    if not is_valid:
        return False, "校验失败:\n" + "\n".join(errors)

    path = CONFIG_DIR / filename

    # Backup
    backup_name = f"{filename}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if path.exists():
        shutil.copy(path, path.parent / backup_name)

    path.write_text(content, encoding="utf-8")

    # Hot reload: rebuild orchestrator
    from sentinel.mgfs.config_loader import build_orchestrator, load_mgfs_config
    from sentinel.mgfs.data import get_price_fetcher
    from sentinel.mgfs.data.eastmoney_fetcher import EastmoneyValuationFetcher

    mgfs_config = load_mgfs_config(CONFIG_DIR / "mgfs_config.yaml")
    fetchers = {
        "valuation": EastmoneyValuationFetcher(),
        "timing": get_price_fetcher(),
    }
    import sentinel.web.dependencies as deps

    new_orch = build_orchestrator(
        mgfs_config,
        config_dir=CONFIG_DIR,
        fetchers=fetchers,
        plugin_kwargs=deps.build_runtime_plugin_kwargs(settings),
    )

    # Replace global orchestrator
    deps._orchestrator = new_orch
    deps._scanner = None  # Force scanner rebuild

    return True, f"配置已保存并热加载。备份: {backup_name}"

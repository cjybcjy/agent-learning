from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import yaml

from sentinel.config import AppSettings

settings = AppSettings()
CONFIG_DIR = settings.resolved_config_dir
ALLOWED_FILES = {
    "moat_static_base.yaml",
    "valuation_sector_routing.yaml",
    "policy_whitelist.yaml",
    "ecosystem_themes.yaml",
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


def validate_config(content: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return False, [f"YAML 语法错误: {e}"]

    if data is None:
        return False, ["YAML 内容为空"]

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


def save_config(filename: str, content: str) -> tuple[bool, str]:
    if filename not in ALLOWED_FILES:
        return False, f"不允许编辑的文件: {filename}"

    is_valid, errors = validate_config(content)
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
    from sentinel.web.dependencies import get_orchestrator
    from sentinel.mgfs.data.eastmoney_fetcher import EastmoneyValuationFetcher

    mgfs_config = load_mgfs_config(CONFIG_DIR / "mgfs_config.yaml")
    fetchers = {"valuation": EastmoneyValuationFetcher()}
    new_orch = build_orchestrator(mgfs_config, config_dir=CONFIG_DIR, fetchers=fetchers)

    # Replace global orchestrator
    import sentinel.web.dependencies as deps
    deps._orchestrator = new_orch
    deps._scanner = None  # Force scanner rebuild

    return True, f"配置已保存并热加载。备份: {backup_name}"

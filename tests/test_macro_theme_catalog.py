from pathlib import Path

import yaml

from sentinel.web.services.theme_service import load_macro_themes


def _write_theme_config(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_load_macro_themes_prefers_structured_catalog(tmp_path):
    config_path = tmp_path / "ecosystem_themes.yaml"
    _write_theme_config(
        config_path,
        {
            "hot_themes": ["Legacy_AI"],
            "macro_themes": [
                {
                    "key": "Self_Reliant_Semiconductors",
                    "label": "半导体自主可控",
                    "policy_anchor": "新质生产力",
                },
                {
                    "key": "Low_Altitude_Economy",
                    "label": "低空经济",
                    "policy_anchor": "新增长引擎",
                },
            ],
        },
    )

    themes = load_macro_themes(config_path)

    assert [theme["key"] for theme in themes] == [
        "Self_Reliant_Semiconductors",
        "Low_Altitude_Economy",
    ]
    assert themes[0]["label"] == "半导体自主可控"
    assert themes[0]["policy_anchor"] == "新质生产力"


def test_default_a_share_macro_theme_catalog_covers_actual_market_themes():
    themes = load_macro_themes()
    keys = {theme["key"] for theme in themes}
    labels = {theme["label"] for theme in themes}

    assert len(themes) >= 12
    assert "AI_Compute_Infrastructure" in keys
    assert "Self_Reliant_Semiconductors" in keys
    assert "Low_Altitude_Economy" in keys
    assert "Embodied_Robotics" in keys
    assert "SOE_Reform_High_Dividend" in keys
    assert "半导体自主可控" in labels
    assert "低空经济" in labels


def test_stock_pool_uses_defined_macro_theme_keys():
    themes = load_macro_themes()
    valid_theme_keys = {theme["key"] for theme in themes}
    moat_config = yaml.safe_load(
        Path("config/moat_static_base.yaml").read_text(encoding="utf-8")
    )
    company_themes = {
        cfg.get("theme")
        for cfg in moat_config.get("companies", {}).values()
        if isinstance(cfg, dict) and cfg.get("theme")
    }

    assert company_themes
    assert company_themes <= valid_theme_keys


def test_embodied_robotics_theme_has_scannable_candidates():
    moat_config = yaml.safe_load(
        Path("config/moat_static_base.yaml").read_text(encoding="utf-8")
    )
    robot_candidates = {
        symbol: cfg
        for symbol, cfg in moat_config.get("companies", {}).items()
        if isinstance(cfg, dict) and cfg.get("theme") == "Embodied_Robotics"
    }

    assert len(robot_candidates) >= 5
    assert all(
        isinstance(cfg.get("fund_heavy_holding_count"), int)
        for cfg in robot_candidates.values()
    )

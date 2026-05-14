from pathlib import Path

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.policy import PolicyFactorPlugin


def test_policy_plugin_reads_sector_multiplier(settings):
    policy_yaml = settings.config_dir / "policy_whitelist.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_multiplier: 1.0
sectors:
  "白酒":
    policy_rating: "neutral"
    multiplier: 1.0
    note: "消费品"
  "新能源汽车":
    policy_rating: "core_support"
    multiplier: 1.2
    note: "十五五核心赛道"
""", encoding="utf-8")

    plugin = PolicyFactorPlugin(config_path=policy_yaml)

    target_baijiu = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity", sector="白酒"
    )
    score_baijiu = plugin.evaluate(target_baijiu)
    assert score_baijiu.details["multiplier"] == 1.0
    assert score_baijiu.details["policy_rating"] == "neutral"

    target_ev = TargetInfo(
        symbol="BYD", market=Market.A_SHARE, asset_class="equity", sector="新能源汽车"
    )
    score_ev = plugin.evaluate(target_ev)
    assert score_ev.details["multiplier"] == 1.2
    assert score_ev.details["policy_rating"] == "core_support"


def test_policy_plugin_uses_override(settings):
    policy_yaml = settings.config_dir / "policy_whitelist.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_multiplier: 1.0
sectors:
  "白酒":
    multiplier: 1.0
overrides:
  "600519":
    multiplier: 1.1
    note: "茅台例外"
""", encoding="utf-8")

    plugin = PolicyFactorPlugin(config_path=policy_yaml)
    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity", sector="白酒"
    )
    score = plugin.evaluate(target)
    assert score.details["multiplier"] == 1.1
    assert "茅台例外" in score.details["note"]


def test_policy_plugin_missing_sector_returns_default(settings):
    policy_yaml = settings.config_dir / "policy_whitelist.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_multiplier: 1.0
sectors: {}
""", encoding="utf-8")

    plugin = PolicyFactorPlugin(config_path=policy_yaml)
    target = TargetInfo(
        symbol="UNKNOWN", market=Market.A_SHARE, asset_class="equity", sector="未知行业"
    )
    score = plugin.evaluate(target)
    assert score.details["multiplier"] == 1.0

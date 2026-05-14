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
    assert score_baijiu.score == 100.0
    assert score_baijiu.factor_key == "policy"
    assert score_baijiu.factor_name == "国策环境"
    assert score_baijiu.confidence == 1.0

    target_ev = TargetInfo(
        symbol="BYD", market=Market.A_SHARE, asset_class="equity", sector="新能源汽车"
    )
    score_ev = plugin.evaluate(target_ev)
    assert score_ev.details["multiplier"] == 1.2
    assert score_ev.details["policy_rating"] == "core_support"
    assert score_ev.score == 120.0
    assert score_ev.factor_key == "policy"
    assert score_ev.factor_name == "国策环境"
    assert score_ev.confidence == 1.0


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
    assert score.score == 110.0
    assert score.factor_key == "policy"
    assert score.factor_name == "国策环境"
    assert score.confidence == 1.0


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
    assert score.score == 100.0
    assert score.factor_key == "policy"
    assert score.factor_name == "国策环境"
    assert score.confidence == 1.0


def test_policy_plugin_sector_none_returns_default():
    plugin = PolicyFactorPlugin(config_path=None)
    target = TargetInfo(
        symbol="UNKNOWN", market=Market.A_SHARE, asset_class="equity", sector=None
    )
    score = plugin.evaluate(target)
    assert score.details["multiplier"] == 1.0
    assert score.details["note"] == ""
    assert score.score == 100.0
    assert score.factor_key == "policy"
    assert score.factor_name == "国策环境"
    assert score.confidence == 1.0


def test_policy_plugin_missing_config_file_returns_default():
    plugin = PolicyFactorPlugin(config_path=None)
    target = TargetInfo(
        symbol="000001", market=Market.A_SHARE, asset_class="equity", sector="银行"
    )
    score = plugin.evaluate(target)
    assert score.details["multiplier"] == 1.0
    assert score.details["note"] == ""
    assert score.score == 100.0
    assert score.factor_key == "policy"
    assert score.factor_name == "国策环境"
    assert score.confidence == 1.0

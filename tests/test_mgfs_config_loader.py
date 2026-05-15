from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.mgfs.config_loader import build_orchestrator, load_mgfs_config
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo
from sentinel.mgfs.orchestrator import MGFSOrchestrator


class TestMoatPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(factor_key="moat", factor_name="护城河", score=80.0)


def test_load_mgfs_config_parses_yaml():
    config_path = Path("/tmp/test_mgfs_config.yaml")
    config_path.write_text("""
version: "1.0"
modules:
  moat:
    enabled: true
    class_path: "tests.test_mgfs_config_loader.TestMoatPlugin"
    config: {}
scoring_formula:
  moat: { weight: 1.0 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
circuit_breakers: {}
rating_thresholds:
  avoid: { min_score: 0.0, label: "Avoid", action: "avoid" }
""", encoding="utf-8")

    config = load_mgfs_config(config_path)
    assert config["version"] == "1.0"
    assert config["modules"]["moat"]["enabled"] is True


def test_load_mgfs_config_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_mgfs_config(Path("/tmp/nonexistent_mgfs_config.yaml"))


def test_build_orchestrator_from_config():
    config_path = Path("/tmp/test_mgfs_config2.yaml")
    config_path.write_text("""
version: "1.0"
modules:
  moat:
    enabled: true
    class_path: "tests.test_mgfs_config_loader.TestMoatPlugin"
    config: {}
scoring_formula:
  moat: { weight: 1.0 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
circuit_breakers: {}
rating_thresholds:
  avoid: { min_score: 0.0, label: "Avoid", action: "avoid" }
""", encoding="utf-8")

    config = load_mgfs_config(config_path)
    orchestrator = build_orchestrator(config)

    assert isinstance(orchestrator, MGFSOrchestrator)
    assert "moat" in orchestrator.plugins


def test_load_plugin_rejects_non_subclass():
    with pytest.raises(TypeError):
        from sentinel.mgfs.config_loader import _load_plugin
        _load_plugin("sentinel.domain.models.Market")


def test_plugin_config_file_includes_valuation():
    from sentinel.mgfs.config_loader import _plugin_config_file

    assert _plugin_config_file("valuation") == "valuation_sector_routing.yaml"
    assert _plugin_config_file("moat") == "moat_static_base.yaml"
    assert _plugin_config_file("policy") == "policy_whitelist.yaml"
    assert _plugin_config_file("unknown") is None

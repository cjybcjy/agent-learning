from __future__ import annotations

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo
from sentinel.mgfs.registry import FactorPluginRegistry


class MockMoatPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(factor_key="moat", factor_name="护城河", score=80.0)


class MockTokenPlugin(BaseFactorPlugin):
    factor_key = "token_metrics"
    factor_name = "Token消耗"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(factor_key="token_metrics", factor_name="Token消耗", score=60.0)


def test_register_and_list_plugins():
    registry = FactorPluginRegistry()
    registry.register(MockMoatPlugin())
    registry.register(MockTokenPlugin())

    plugins = registry.list_by_keys(["moat", "token_metrics"])
    assert len(plugins) == 2
    assert plugins[0].factor_key == "moat"
    assert plugins[1].factor_key == "token_metrics"


def test_list_plugins_returns_copy():
    registry = FactorPluginRegistry()
    registry.register(MockMoatPlugin())

    first = registry.list_by_keys(["moat"])
    second = registry.list_by_keys(["moat"])
    assert first is not second


def test_missing_plugin_raises_keyerror():
    registry = FactorPluginRegistry()
    with pytest.raises(KeyError, match="factor not registered: missing"):
        registry.list_by_keys(["missing"])

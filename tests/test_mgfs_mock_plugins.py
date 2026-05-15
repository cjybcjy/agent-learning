from __future__ import annotations

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.valuation import ValuationFactorPlugin
from sentinel.mgfs.plugins.timing import TimingFactorPlugin


def test_valuation_plugin_returns_real_score():
    plugin = ValuationFactorPlugin()
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    score = plugin.evaluate(target)

    assert score.factor_key == "valuation"
    assert score.factor_name == "估值水位"
    assert score.weight == 0.2
    assert 0 <= score.score <= 100
    assert "zone" in score.details


def test_timing_plugin_returns_mock_score():
    plugin = TimingFactorPlugin()
    target = TargetInfo(symbol="BTC", market=Market.CRYPTO, asset_class="crypto")
    score = plugin.evaluate(target)

    assert score.factor_key == "timing"
    assert score.factor_name == "量化择时"
    assert score.score == 50.0
    assert score.details["note"] == "mock implementation — Step 2"

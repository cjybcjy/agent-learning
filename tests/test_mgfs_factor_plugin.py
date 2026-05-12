from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import (
    AlertLevel,
    BaseFactorPlugin,
    FactorScore,
    TargetInfo,
)


def test_target_info_is_frozen_dataclass():
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    assert target.symbol == "600519"
    assert target.market == Market.A_SHARE
    assert target.asset_class == "equity"


def test_factor_score_normalized_score():
    score = FactorScore(factor_key="moat", factor_name="护城河", score=75.0, max_score=100.0)
    assert score.normalized_score == 0.75


def test_factor_score_normalized_with_zero_max():
    score = FactorScore(factor_key="moat", factor_name="护城河", score=10.0, max_score=0.0)
    assert score.normalized_score == 0.0


def test_alert_level_enum_values():
    assert AlertLevel.HARD_VETO.value == "hard_veto"
    assert AlertLevel.SOFT_VETO.value == "soft_veto"
    assert AlertLevel.YELLOW_WARNING.value == "yellow_warning"
    assert AlertLevel.GREEN_PASS.value == "green_pass"


def test_base_factor_plugin_is_abstract():
    import inspect
    assert inspect.isabstract(BaseFactorPlugin)
    assert "evaluate" in BaseFactorPlugin.__abstractmethods__

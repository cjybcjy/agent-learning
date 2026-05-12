from __future__ import annotations

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo
from sentinel.mgfs.orchestrator import MGFSOrchestrator


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


def test_orchestrator_evaluates_plugins_and_computes_raw_total():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin(), MockTokenPlugin()],
        scoring_weights={"moat": 0.5, "token_metrics": 0.5},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 90.0, "label": "Strong Buy", "action": "buy"},
            {"min_score": 0.0, "label": "Avoid", "action": "avoid"},
        ],
    )
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    assert decision.target.symbol == "600519"
    assert "moat" in decision.factor_scores
    assert "token_metrics" in decision.factor_scores
    # raw_total = (0.8 * 100 * 0.5 + 0.6 * 100 * 0.5) / 1.0 = 70.0
    assert decision.raw_total == 70.0
    assert decision.policy_multiplier == 1.0
    assert decision.final_score == 70.0


def test_orchestrator_plugin_failure_returns_fallback():
    class BrokenPlugin(BaseFactorPlugin):
        factor_key = "broken"
        factor_name = "故障插件"

        def evaluate(self, target: TargetInfo) -> FactorScore:
            raise RuntimeError("boom")

    orchestrator = MGFSOrchestrator(
        plugins=[BrokenPlugin()],
        scoring_weights={"broken": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "avoid"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    assert decision.factor_scores["broken"].score == 0.0
    assert decision.factor_scores["broken"].confidence == 0.0
    assert "评估失败" in decision.factor_scores["broken"].warnings[0]


def test_classify_rating_fallback():
    orchestrator = MGFSOrchestrator(
        plugins=[],
        scoring_weights={},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 60.0, "label": "Hold", "action": "wait"},
        ],
    )
    from sentinel.mgfs.factor_plugin import AlertLevel
    rating, action = orchestrator._classify_rating(0.0, AlertLevel.GREEN_PASS)
    assert rating == "Avoid"
    assert action == "回避"

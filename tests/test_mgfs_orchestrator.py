from __future__ import annotations

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import AlertLevel, BaseFactorPlugin, FactorScore, TargetInfo
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


def test_orchestrator_policy_multiplier_applied():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"core_support": 1.2, "neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "avoid"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="core_support")

    assert decision.policy_multiplier == 1.2
    assert decision.final_score == 96.0  # 80 * 1.2


def test_orchestrator_circuit_breaker_triggers():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[
            {
                "enabled": True,
                "rule": "moat_score < 100",
                "action": "soft_veto",
                "alert_level": "soft_veto",
                "message": "护城河评分过低",
            }
        ],
        rating_thresholds=[
            {"min_score": 90.0, "label": "Strong Buy", "action": "buy"},
            {"min_score": 0.0, "label": "Avoid", "action": "avoid"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    assert len(decision.circuit_breakers_triggered) == 1
    assert decision.alert_level == AlertLevel.SOFT_VETO
    assert decision.rating == "Avoid"


def test_orchestrator_hard_veto_forces_avoid():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[
            {
                "enabled": True,
                "rule": "policy_rating == 'veto'",
                "action": "hard_veto",
                "alert_level": "hard_veto",
                "message": "一票否决",
            }
        ],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "avoid"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="veto")

    assert decision.alert_level == AlertLevel.HARD_VETO
    assert decision.rating == "Avoid"
    assert "一票否决" in decision.action


def test_orchestrator_rating_classification():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 90.0, "label": "Strong Buy", "action": "重仓出击"},
            {"min_score": 75.0, "label": "Accumulate", "action": "分批建仓"},
            {"min_score": 60.0, "label": "Hold/Watch", "action": "等待拐点"},
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")

    # Score 80 falls into Accumulate (75-90)
    decision = orchestrator.evaluate(target, policy_rating="neutral")
    assert decision.rating == "Accumulate"
    assert decision.action == "分批建仓"


def test_disabled_circuit_breaker_does_not_trigger():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[
            {
                "enabled": False,
                "rule": "moat_score < 100",
                "action": "soft_veto",
                "alert_level": "soft_veto",
                "message": "should not trigger",
            }
        ],
        rating_thresholds=[{"min_score": 0.0, "label": "Avoid", "action": "avoid"}],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")
    assert len(decision.circuit_breakers_triggered) == 0
    assert decision.alert_level == AlertLevel.GREEN_PASS


def test_malformed_rule_logs_warning():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[
            {
                "enabled": True,
                "rule": "this is not valid python",
                "action": "soft_veto",
                "alert_level": "soft_veto",
                "message": "malformed",
            }
        ],
        rating_thresholds=[{"min_score": 0.0, "label": "Avoid", "action": "avoid"}],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")
    # Should not crash, should not trigger
    assert len(decision.circuit_breakers_triggered) == 0


def test_invalid_alert_level_defaults_to_yellow():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[
            {
                "enabled": True,
                "rule": "moat_score < 100",
                "action": "soft_veto",
                "alert_level": "invalid_level",
                "message": "bad level",
            }
        ],
        rating_thresholds=[{"min_score": 0.0, "label": "Avoid", "action": "avoid"}],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")
    # Should not crash, should default to yellow_warning
    assert len(decision.circuit_breakers_triggered) == 1
    assert decision.alert_level == AlertLevel.YELLOW_WARNING


def test_all_plugins_crash_returns_error_rating():
    class BrokenMoat(BaseFactorPlugin):
        factor_key = "moat"
        factor_name = "护城河"

        def evaluate(self, target: TargetInfo) -> FactorScore:
            raise RuntimeError("boom")

    class BrokenToken(BaseFactorPlugin):
        factor_key = "token_metrics"
        factor_name = "Token消耗"

        def evaluate(self, target: TargetInfo) -> FactorScore:
            raise ValueError("kapow")

    orchestrator = MGFSOrchestrator(
        plugins=[BrokenMoat(), BrokenToken()],
        scoring_weights={"moat": 0.5, "token_metrics": 0.5},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[{"min_score": 0.0, "label": "Avoid", "action": "avoid"}],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    assert decision.rating == "Error"
    assert decision.action == "系统异常，人工复核"
    assert decision.alert_level == AlertLevel.YELLOW_WARNING
    assert decision.raw_total == 0.0
    assert decision.final_score == 0.0
    assert decision.factor_scores["moat"].confidence == 0.0
    assert decision.factor_scores["token_metrics"].confidence == 0.0


class CryptoOnlyPlugin(BaseFactorPlugin):
    factor_key = "crypto_only"
    factor_name = "Crypto专用"

    def is_applicable(self, target: TargetInfo) -> bool:
        return target.asset_class == "crypto"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=80.0,
        )


def test_orchestrator_skips_non_applicable_plugins():
    orchestrator = MGFSOrchestrator(
        plugins=[CryptoOnlyPlugin()],
        scoring_weights={"crypto_only": 0.3},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target)

    assert "crypto_only" not in decision.factor_scores
    assert decision.raw_total == 0.0


def test_orchestrator_includes_applicable_plugins():
    orchestrator = MGFSOrchestrator(
        plugins=[CryptoOnlyPlugin()],
        scoring_weights={"crypto_only": 0.3},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )
    target = TargetInfo(symbol="BTC", market=Market.CRYPTO, asset_class="crypto")
    decision = orchestrator.evaluate(target)

    assert "crypto_only" in decision.factor_scores
    assert decision.factor_scores["crypto_only"].score == 80.0


def test_orchestrator_computes_overall_confidence():
    class HighConfPlugin(BaseFactorPlugin):
        factor_key = "high"
        factor_name = "高置信度"

        def evaluate(self, target: TargetInfo) -> FactorScore:
            return FactorScore(factor_key="high", factor_name="高置信度", score=80.0, confidence=1.0)

    class LowConfPlugin(BaseFactorPlugin):
        factor_key = "low"
        factor_name = "低置信度"

        def evaluate(self, target: TargetInfo) -> FactorScore:
            return FactorScore(factor_key="low", factor_name="低置信度", score=60.0, confidence=0.5)

    orchestrator = MGFSOrchestrator(
        plugins=[HighConfPlugin(), LowConfPlugin()],
        scoring_weights={"high": 0.5, "low": 0.5},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target)

    # overall confidence = (1.0*0.5 + 0.5*0.5) / (0.5+0.5) = 0.75
    assert decision.report_sections.get("overall_confidence") == 0.75
    assert decision.report_sections.get("watermark") == "[数据部分缺失]"


def test_orchestrator_low_confidence_adds_watermark():
    class ZeroConfPlugin(BaseFactorPlugin):
        factor_key = "zero"
        factor_name = "零置信度"

        def evaluate(self, target: TargetInfo) -> FactorScore:
            return FactorScore(factor_key="zero", factor_name="零置信度", score=50.0, confidence=0.0)

    orchestrator = MGFSOrchestrator(
        plugins=[ZeroConfPlugin()],
        scoring_weights={"zero": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target)

    assert decision.report_sections.get("overall_confidence") == 0.0
    assert decision.report_sections.get("watermark") == "[数据残缺 / 评估挂起]"

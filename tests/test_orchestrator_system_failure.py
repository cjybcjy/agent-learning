from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import (
    AlertLevel,
    BaseFactorPlugin,
    FactorScore,
    TargetInfo,
)
from sentinel.mgfs.orchestrator import MGFSOrchestrator


class FailingTimingPlugin(BaseFactorPlugin):
    """Simulates a timing plugin that crashes due to network failure."""

    factor_key = "timing"
    factor_name = "量化择时"
    default_weight = 0.1

    def evaluate(self, target: TargetInfo) -> FactorScore:
        raise ConnectionError("模拟网络断连：K线数据获取失败")


class StableMoatPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河深度"
    default_weight = 0.5

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=85.0,
            weight=self.default_weight,
            confidence=0.85,
        )


class StableValuationPlugin(BaseFactorPlugin):
    factor_key = "valuation"
    factor_name = "估值水位"
    default_weight = 0.3

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=70.0,
            weight=self.default_weight,
            confidence=0.75,
            details={"primary_percentile": 35.0},
        )


@pytest.fixture
def orchestrator() -> MGFSOrchestrator:
    return MGFSOrchestrator(
        plugins=[
            StableMoatPlugin(),
            StableValuationPlugin(),
            FailingTimingPlugin(),
        ],
        scoring_weights={"moat": 0.5, "valuation": 0.3, "timing": 0.1},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 90.0, "label": "Strong Buy", "action": "重仓出击"},
            {"min_score": 75.0, "label": "Accumulate", "action": "分批建仓"},
            {"min_score": 60.0, "label": "Hold/Watch", "action": "等待拐点"},
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )


def test_timing_network_failure_downgrades_to_hold_watch(orchestrator: MGFSOrchestrator):
    """When timing plugin fails due to network error, rating must drop to Hold/Watch."""
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    # Timing should have system-failure marker
    timing = decision.factor_scores.get("timing")
    assert timing is not None
    assert timing.confidence == 0.0
    assert any("系统故障" in w for w in timing.warnings)

    # Rating must NOT be Strong Buy / Accumulate
    assert decision.rating == "Hold/Watch"
    assert decision.action == "等待拐点"
    assert decision.alert_level == AlertLevel.SOFT_VETO

    # Watermark must indicate system failure protection
    assert "系统故障" in decision.report_sections.get("watermark", "")
    assert "置信度熔断保护中" in decision.report_sections.get("watermark", "")


def test_timing_failure_does_not_inflate_score_via_weight_redistribution(
    orchestrator: MGFSOrchestrator,
):
    """Without timing, score should drop because timing weight contributes 0,
    not inflate because other weights are redistributed."""
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    # Expected raw total with original weights (timing = 0):
    # moat: 85/100 * 100 * 0.5 = 42.5
    # valuation: 70/100 * 100 * 0.3 = 21.0
    # timing: 0 * 100 * 0.1 = 0
    # total = 63.5, weight_sum = 0.9, raw_total = 63.5 / 0.9 = 70.56
    # final_score = 70.56 * 1.0 = 70.56
    # With weight redistribution (BUG):
    # moat: 85 * 0.625 = 53.125, valuation: 70 * 0.375 = 26.25
    # raw_total = 79.375
    # So we assert final_score < 75 (not Accumulate territory)
    assert decision.final_score < 75.0, (
        f"Score inflated to {decision.final_score} due to weight redistribution. "
        "Expected < 75 with timing failure."
    )

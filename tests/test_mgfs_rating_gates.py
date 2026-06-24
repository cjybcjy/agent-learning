from sentinel.mgfs.factor_plugin import FactorScore
from sentinel.mgfs.rating_gates import RatingGateEvaluator


def test_rating_gate_without_rules_passes_for_legacy_thresholds():
    threshold = {"min_score": 90.0, "label": "Strong Buy", "action": "buy"}
    result = RatingGateEvaluator().evaluate(
        threshold=threshold,
        factor_scores={},
        overall_confidence=0.0,
    )

    assert result.passed is True
    assert result.failures == []


def test_rating_gate_passes_with_complete_factor_evidence():
    threshold = {
        "min_score": 90.0,
        "label": "Strong Buy",
        "action": "buy",
        "min_overall_confidence": 0.8,
        "required_factors": {
            "moat": {
                "min_score": 80.0,
                "min_confidence": 0.8,
                "details": {"evidence_coverage": {"min": 0.8}},
            },
            "valuation": {
                "min_confidence": 0.7,
                "details": {"zone": {"in": ["strong_buy"]}},
            },
        },
    }
    scores = {
        "moat": FactorScore(
            factor_key="moat",
            factor_name="护城河",
            score=86.0,
            confidence=0.9,
            details={"evidence_coverage": 0.92},
        ),
        "valuation": FactorScore(
            factor_key="valuation",
            factor_name="估值",
            score=95.0,
            confidence=0.8,
            details={"zone": "strong_buy"},
        ),
    }

    result = RatingGateEvaluator().evaluate(
        threshold=threshold,
        factor_scores=scores,
        overall_confidence=0.84,
    )

    assert result.passed is True
    assert result.failures == []


def test_rating_gate_reports_missing_and_low_evidence():
    threshold = {
        "min_score": 90.0,
        "label": "Strong Buy",
        "action": "buy",
        "min_overall_confidence": 0.8,
        "required_factors": {
            "moat": {
                "min_score": 80.0,
                "min_confidence": 0.8,
                "details": {"evidence_coverage": {"min": 0.8}},
            },
            "valuation": {
                "min_confidence": 0.7,
                "details": {"zone": {"in": ["strong_buy"]}},
            },
            "timing": {"min_confidence": 0.5},
        },
    }
    scores = {
        "moat": FactorScore(
            factor_key="moat",
            factor_name="护城河",
            score=78.0,
            confidence=0.7,
            details={"evidence_coverage": 0.25},
        ),
        "valuation": FactorScore(
            factor_key="valuation",
            factor_name="估值",
            score=90.0,
            confidence=0.6,
            details={"zone": "accumulate"},
        ),
    }

    result = RatingGateEvaluator().evaluate(
        threshold=threshold,
        factor_scores=scores,
        overall_confidence=0.74,
    )

    assert result.passed is False
    paths = {failure.path for failure in result.failures}
    assert "overall_confidence" in paths
    assert "moat.score" in paths
    assert "moat.confidence" in paths
    assert "moat.details.evidence_coverage" in paths
    assert "valuation.confidence" in paths
    assert "valuation.details.zone" in paths
    assert "timing" in paths
    assert all(failure.threshold_label == "Strong Buy" for failure in result.failures)

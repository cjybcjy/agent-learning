import pytest

from sentinel.mgfs.config_validator import (
    MGFSConfigValidationError,
    validate_mgfs_config,
)


def _valid_config() -> dict:
    return {
        "version": "1.0",
        "modules": {
            "moat": {
                "enabled": True,
                "class_path": "tests.test_mgfs_config_loader.TestMoatPlugin",
            }
        },
        "scoring_formula": {"moat": {"weight": 1.0}},
        "policy_multiplier": {"neutral": {"multiplier": 1.0}},
        "circuit_breakers": {
            "min_moat": {
                "enabled": True,
                "rule": "moat_score < 30",
                "alert_level": "soft_veto",
                "message": "护城河过低",
            }
        },
        "rating_thresholds": {
            "strong_buy": {
                "min_score": 90.0,
                "label": "Strong Buy",
                "action": "重仓出击",
                "min_overall_confidence": 0.8,
                "required_factors": {
                    "moat": {
                        "min_score": 80.0,
                        "min_confidence": 0.8,
                        "details": {"evidence_coverage": {"min": 0.8}},
                    }
                },
            },
            "avoid": {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        },
    }


def test_valid_mgfs_config_returns_no_validation_issues():
    issues = validate_mgfs_config(_valid_config())

    assert issues == []


def test_validator_reports_invalid_weights_circuit_breakers_and_rating_gates():
    config = _valid_config()
    config["scoring_formula"]["moat"]["weight"] = -0.2
    config["circuit_breakers"]["min_moat"]["alert_level"] = "panic"
    config["rating_thresholds"]["strong_buy"]["min_overall_confidence"] = 1.5
    config["rating_thresholds"]["strong_buy"]["required_factors"]["moat"]["details"][
        "evidence_coverage"
    ] = {"min": "high"}

    issues = validate_mgfs_config(config)
    paths = {issue.path for issue in issues}

    assert "scoring_formula.moat.weight" in paths
    assert "circuit_breakers.min_moat.alert_level" in paths
    assert "rating_thresholds.strong_buy.min_overall_confidence" in paths
    assert (
        "rating_thresholds.strong_buy.required_factors.moat.details.evidence_coverage.min"
        in paths
    )


def test_validator_raises_with_issue_paths_when_requested():
    config = _valid_config()
    config["rating_thresholds"]["avoid"].pop("action")

    with pytest.raises(MGFSConfigValidationError) as exc_info:
        validate_mgfs_config(config, raise_on_error=True)

    assert "rating_thresholds.avoid.action" in str(exc_info.value)
    assert exc_info.value.issues[0].path == "rating_thresholds.avoid.action"

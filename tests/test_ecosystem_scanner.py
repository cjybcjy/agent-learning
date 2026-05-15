from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import AlertLevel, FactorScore, TargetInfo
from sentinel.mgfs.orchestrator import InvestmentDecision
from sentinel.mgfs.scanner import EcosystemScanner, ScanResult


def _make_decision(
    target: TargetInfo,
    *,
    moat_score: float = 80.0,
    valuation_zone: str = "strong_buy",
    alert_level: AlertLevel = AlertLevel.GREEN_PASS,
    final_score: float = 85.0,
) -> InvestmentDecision:
    return InvestmentDecision(
        target=target,
        generated_at=datetime.now(tz=timezone.utc),
        factor_scores={
            "moat": FactorScore(
                factor_key="moat",
                factor_name="护城河",
                score=moat_score,
            ),
            "valuation": FactorScore(
                factor_key="valuation",
                factor_name="估值水位",
                score=70.0,
                details={"zone": valuation_zone},
            ),
        },
        raw_total=final_score,
        policy_multiplier=1.0,
        final_score=final_score,
        rating="Accumulate",
        action="分批建仓",
        circuit_breakers_triggered=[],
        alert_level=alert_level,
    )


def test_scanner_filters_by_theme_and_role(tmp_path: Path) -> None:
    config_path = tmp_path / "moat.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "companies": {
                    "SYM1": {
                        "name": "Alpha",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "upstream_resource",
                    },
                    "SYM2": {
                        "name": "Beta",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "downstream_app",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    orchestrator = MagicMock()

    def mock_evaluate(target: TargetInfo, **kwargs: object) -> InvestmentDecision:
        return _make_decision(target, final_score=90.0 if target.symbol == "SYM1" else 70.0)

    orchestrator.evaluate = mock_evaluate

    scanner = EcosystemScanner(
        orchestrator=orchestrator,
        moat_config_path=config_path,
    )
    result = scanner.scan_theme(
        theme_name="AI",
        target_roles=["upstream_resource"],
    )

    assert isinstance(result, ScanResult)
    assert result.theme == "AI"
    assert result.total_candidates == 2
    assert result.filtered_count == 1
    assert len(result.reports) == 1
    assert result.reports[0].target.symbol == "SYM1"
    assert result.summary["skipped_by_role"] == 1
    assert result.summary["passed_all_gates"] == 1


def test_scanner_skips_veto_and_low_moat(tmp_path: Path) -> None:
    config_path = tmp_path / "moat.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "companies": {
                    "GOOD": {
                        "name": "Good Co",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "upstream_resource",
                    },
                    "VETO": {
                        "name": "Veto Co",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "upstream_resource",
                    },
                    "LOW": {
                        "name": "Low Moat",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "upstream_resource",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    orchestrator = MagicMock()

    def mock_evaluate(target: TargetInfo, **kwargs: object) -> InvestmentDecision:
        if target.symbol == "GOOD":
            return _make_decision(target, moat_score=80.0, alert_level=AlertLevel.GREEN_PASS, final_score=85.0)
        if target.symbol == "VETO":
            return _make_decision(target, moat_score=80.0, alert_level=AlertLevel.HARD_VETO, final_score=50.0)
        if target.symbol == "LOW":
            return _make_decision(target, moat_score=40.0, alert_level=AlertLevel.GREEN_PASS, final_score=30.0)
        raise RuntimeError("Unknown symbol")

    orchestrator.evaluate = mock_evaluate

    scanner = EcosystemScanner(
        orchestrator=orchestrator,
        moat_config_path=config_path,
    )
    result = scanner.scan_theme(theme_name="AI")

    assert result.total_candidates == 3
    assert result.filtered_count == 1
    assert len(result.reports) == 1
    assert result.reports[0].target.symbol == "GOOD"
    assert result.summary["skipped_by_veto"] == 1
    assert result.summary["skipped_by_moat"] == 1
    assert result.summary["passed_all_gates"] == 1

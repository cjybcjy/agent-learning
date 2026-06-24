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


def test_scanner_filters_by_heavy_fund_count_rank(tmp_path: Path) -> None:
    config_path = tmp_path / "moat.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "companies": {
                    "TOP1": {
                        "name": "Top Fund Favorite",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "upstream_resource",
                        "fund_heavy_holding_count": 35,
                    },
                    "TOP2": {
                        "name": "Second Favorite",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "upstream_resource",
                        "fund_heavy_holding_count": 20,
                    },
                    "TAIL": {
                        "name": "Tail Holding",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "upstream_resource",
                        "fund_heavy_holding_count": 5,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    orchestrator = MagicMock()

    def mock_evaluate(target: TargetInfo, **kwargs: object) -> InvestmentDecision:
        return _make_decision(target, final_score=80.0)

    orchestrator.evaluate = mock_evaluate

    scanner = EcosystemScanner(
        orchestrator=orchestrator,
        moat_config_path=config_path,
    )
    result = scanner.scan_theme(theme_name="AI", fund_rank_limit=2)

    assert [report.target.symbol for report in result.reports] == ["TOP1", "TOP2"]
    assert [report.target.fund_heavy_holding_rank for report in result.reports] == [1, 2]
    assert result.reports[0].target.fund_heavy_holding_count == 35
    assert result.summary["fund_rank_limit"] == 2
    assert result.summary["skipped_by_fund_rank"] == 1
    assert result.summary["evaluated"] == 2


def test_scanner_preview_counts_candidates_without_evaluation(tmp_path: Path) -> None:
    config_path = tmp_path / "moat.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "companies": {
                    "TOP1": {
                        "name": "Top Fund Favorite",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "upstream_resource",
                        "fund_heavy_holding_count": 35,
                    },
                    "TOP2": {
                        "name": "Second Favorite",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "upstream_resource",
                        "fund_heavy_holding_count": 20,
                    },
                    "APP": {
                        "name": "Downstream App",
                        "sector": "Tech",
                        "theme": "AI",
                        "ecosystem_role": "downstream_app",
                        "fund_heavy_holding_count": 5,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    orchestrator = MagicMock()
    scanner = EcosystemScanner(
        orchestrator=orchestrator,
        moat_config_path=config_path,
    )

    summary = scanner.preview_theme(
        theme_name="AI",
        target_roles=["upstream_resource"],
        fund_rank_limit=1,
    )

    assert summary["total_candidates"] == 3
    assert summary["evaluated"] == 1
    assert summary["skipped_by_role"] == 1
    assert summary["skipped_by_fund_rank"] == 1
    orchestrator.evaluate.assert_not_called()


def test_build_ecosystem_report_generates_card():
    from sentinel.publishers.mgfs_report import build_ecosystem_scan_report
    from sentinel.mgfs.scanner import ScanResult
    from sentinel.mgfs.orchestrator import InvestmentDecision
    from sentinel.mgfs.factor_plugin import TargetInfo, FactorScore, AlertLevel
    from sentinel.domain.models import Market
    from datetime import datetime

    target = TargetInfo(
        symbol="600900", market=Market.A_SHARE, asset_class="equity",
        name="长江电力", sector="电力",
        theme="AI_Compute_Infrastructure", ecosystem_role="symbiotic_infra",
    )
    decision = InvestmentDecision(
        target=target,
        generated_at=datetime.now(),
        factor_scores={
            "moat": FactorScore(factor_key="moat", factor_name="护城河", score=95, confidence=0.9, details={"zone": "strong_buy"}),
            "valuation": FactorScore(factor_key="valuation", factor_name="估值", score=32, confidence=0.8, details={"zone": "accumulate"}),
        },
        raw_total=88.5,
        policy_multiplier=1.1,
        final_score=97.35,
        rating="Strong Buy",
        action="建议配底仓",
        circuit_breakers_triggered=[],
        alert_level=AlertLevel.GREEN_PASS,
    )
    result = ScanResult(
        theme="AI_Compute_Infrastructure",
        total_candidates=5,
        filtered_count=1,
        reports=[decision],
        summary={"skipped_by_veto": 3, "skipped_by_zone": 1},
    )

    card = build_ecosystem_scan_report(result)
    assert card["header"]["title"]["content"] == "📊 MGFS 产业链价值扫描报告"
    assert "AI_Compute_Infrastructure" in str(card)
    assert "600900" in str(card)
    assert "共生基础设施" in str(card)

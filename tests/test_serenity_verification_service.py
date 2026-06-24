from __future__ import annotations

from pathlib import Path

import yaml

from sentinel.web.services.serenity_verification_service import (
    SerenityVerificationService,
)


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_serenity_verification_plan_maps_moat_gaps_to_sources_and_metrics(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    moat_path = config_dir / "moat_static_base.yaml"
    original_moat = {
        "companies": {
            "600519": {
                "name": "贵州茅台",
                "sector": "白酒",
                "base_score": {
                    "brand_premium": {
                        "score": 95,
                        "note": "社交货币属性，议价能力极强",
                    },
                    "cost_advantage": {
                        "score": 70,
                        "note": "毛利率高但原料成本有波动",
                        "source": "2025 年报",
                        "as_of": "2026-04-01",
                        "confidence": 0.72,
                        "bear_case": "原料价格上行会削弱成本优势",
                    },
                },
            }
        }
    }
    _write_yaml(moat_path, original_moat)

    plan = SerenityVerificationService(config_dir=config_dir).build_plan(
        symbol="600519",
        market="A_SHARE",
    )

    assert plan.symbol == "600519"
    assert plan.boundary == "read_only_verification_plan"
    assert plan.company_name == "贵州茅台"
    assert len(plan.evidence_gaps) == 1
    gap = plan.evidence_gaps[0]
    assert gap.dimension == "brand_premium"
    assert gap.missing_fields == ["source", "as_of", "confidence", "bear_case"]
    assert "年报" in gap.source_paths[0]
    assert "source/as_of/confidence/bear_case" in gap.config_patch_hint

    metric_names = {target.metric_name for target in plan.metric_targets}
    assert {
        "roic_sustainability",
        "gmoat_stability",
        "rd_efficiency",
        "debt_ratio_deterioration",
        "goodwill_ratio",
        "operating_cashflow_ratio",
    }.issubset(metric_names)
    cashflow_target = next(
        target for target in plan.metric_targets
        if target.metric_name == "operating_cashflow_ratio"
    )
    assert cashflow_target.target_table == "safety_metrics"
    assert "经营活动现金流量净额" in cashflow_target.financial_items
    assert yaml.safe_load(moat_path.read_text(encoding="utf-8")) == original_moat

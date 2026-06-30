from pathlib import Path

import yaml

from sentinel.web.services.config_change_service import ConfigChangeService
from sentinel.web.services.research_agent_service import ResearchSuggestion


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _base_configs(config_dir: Path) -> None:
    config_dir.mkdir()
    _write_yaml(
        config_dir / "ecosystem_themes.yaml",
        {
            "macro_themes": [{"key": "Advanced_Manufacturing", "label": "高端制造"}],
            "hot_themes": ["Advanced_Manufacturing"],
        },
    )
    _write_yaml(
        config_dir / "valuation_sector_routing.yaml",
        {
            "sector_to_archetype": {"半导体": "saas_and_tech"},
            "default_archetype": "traditional_growth",
        },
    )


def test_scan_proposes_add_sector_mapping_for_unmapped_moat_sector(tmp_path: Path):
    config_dir = tmp_path / "config"
    _base_configs(config_dir)
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {
            "companies": {
                "000001": {
                    "name": "Alpha",
                    "sector": "家电",
                    "theme": "Advanced_Manufacturing",
                }
            }
        },
    )

    service = ConfigChangeService(config_dir=config_dir, store_path=tmp_path / "decisions.json")
    proposals = service.scan_proposals()

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.action == "add"
    assert proposal.config_file == "valuation_sector_routing.yaml"
    assert proposal.path == "sector_to_archetype.家电"
    assert proposal.proposed_value == "traditional_growth"


def test_approve_add_sector_mapping_updates_yaml(tmp_path: Path):
    config_dir = tmp_path / "config"
    _base_configs(config_dir)
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {
            "companies": {
                "000001": {
                    "name": "Alpha",
                    "sector": "新能源",
                    "theme": "Advanced_Manufacturing",
                }
            }
        },
    )
    service = ConfigChangeService(config_dir=config_dir, store_path=tmp_path / "decisions.json")
    proposal = service.scan_proposals()[0]

    applied = service.approve_proposal(proposal.id)

    updated = yaml.safe_load((config_dir / "valuation_sector_routing.yaml").read_text(encoding="utf-8"))
    assert applied.status == "approved"
    assert updated["sector_to_archetype"]["新能源"] == "saas_and_tech"


def test_approve_delete_invalid_theme_candidate_updates_yaml(tmp_path: Path):
    config_dir = tmp_path / "config"
    _base_configs(config_dir)
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {
            "companies": {
                "000001": {
                    "name": "Alpha",
                    "sector": "半导体",
                    "theme": "Missing_Theme",
                }
            }
        },
    )
    service = ConfigChangeService(config_dir=config_dir, store_path=tmp_path / "decisions.json")
    proposal = service.scan_proposals()[0]

    assert proposal.action == "delete"
    assert proposal.path == "companies.000001"
    service.approve_proposal(proposal.id)

    updated = yaml.safe_load((config_dir / "moat_static_base.yaml").read_text(encoding="utf-8"))
    assert "000001" not in updated["companies"]


def test_reject_proposal_hides_it_from_pending_queue(tmp_path: Path):
    config_dir = tmp_path / "config"
    _base_configs(config_dir)
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {
            "companies": {
                "000001": {
                    "name": "Alpha",
                    "sector": "家电",
                    "theme": "Advanced_Manufacturing",
                }
            }
        },
    )
    service = ConfigChangeService(config_dir=config_dir, store_path=tmp_path / "decisions.json")
    proposal = service.scan_proposals()[0]

    rejected = service.reject_proposal(proposal.id)

    assert rejected.status == "rejected"
    assert service.scan_proposals() == []


def test_queue_agent_policy_suggestion_adds_manual_confirmation_item(tmp_path: Path):
    config_dir = tmp_path / "config"
    _base_configs(config_dir)
    _write_yaml(config_dir / "moat_static_base.yaml", {"companies": {}})
    _write_yaml(
        config_dir / "policy_whitelist.yaml",
        {
            "last_updated": "2026-06-20",
            "sectors": {"人工智能": {"policy_rating": "core_support", "multiplier": 1.2}},
        },
    )
    service = ConfigChangeService(config_dir=config_dir, store_path=tmp_path / "decisions.json")
    suggestion = ResearchSuggestion(
        id="policy-s1",
        category="外部信号",
        title="政策白名单有新外部信号待复核",
        target="人工智能",
        config_file="policy_whitelist.yaml",
        rationale="人工智能+行动有新政策信号，需要人工复核。",
        proposed_change="核验原文后再决定是否调整 policy_rating。",
        confidence=0.72,
        impact="高",
        evidence=[],
        counter_evidence=[],
    )

    queued = service.queue_agent_suggestion(suggestion)

    assert len(queued) == 1
    proposal = queued[0]
    assert proposal.action == "add"
    assert proposal.config_file == "policy_whitelist.yaml"
    assert proposal.path.startswith("review_queue.")
    assert proposal.proposed_value["target"] == "人工智能"
    assert "人工智能" in service.scan_proposals()[0].title


def test_approve_agent_moat_evidence_queue_adds_review_item_without_faking_evidence(
    tmp_path: Path,
):
    config_dir = tmp_path / "config"
    _base_configs(config_dir)
    _write_yaml(config_dir / "policy_whitelist.yaml", {"last_updated": "2026-06-20"})
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {
            "companies": {
                "600519": {
                    "name": "贵州茅台",
                    "sector": "白酒",
                    "theme": "Advanced_Manufacturing",
                    "base_score": {
                        "brand_premium": {"score": 95, "note": "品牌溢价强"}
                    },
                }
            }
        },
    )
    service = ConfigChangeService(config_dir=config_dir, store_path=tmp_path / "decisions.json")
    suggestion = ResearchSuggestion(
        id="moat-e1",
        category="证据覆盖",
        title="护城河评分缺少证据字段",
        target="base_score",
        config_file="moat_static_base.yaml",
        rationale="护城河静态评分缺少 source/as_of/confidence/bear_case。",
        proposed_change="补充真实证据字段，再决定是否调整分数。",
        confidence=0.88,
        impact="高",
        evidence=[],
        counter_evidence=[],
    )

    queued = service.queue_agent_suggestion(suggestion)
    proposal = queued[0]
    applied = service.approve_proposal(proposal.id)

    updated = yaml.safe_load((config_dir / "moat_static_base.yaml").read_text(encoding="utf-8"))
    score_item = updated["companies"]["600519"]["base_score"]["brand_premium"]
    assert applied.status == "approved"
    assert "source" not in score_item
    review_items = updated["evidence_review_queue"]
    assert any(item["symbol"] == "600519" for item in review_items.values())

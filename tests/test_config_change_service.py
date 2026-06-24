from pathlib import Path

import yaml

from sentinel.web.services.config_change_service import ConfigChangeService


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

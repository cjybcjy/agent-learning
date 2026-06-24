from pathlib import Path

import yaml

from sentinel.domain.models import Market
from sentinel.mgfs.target_resolver import TargetResolver


def test_target_resolver_enriches_symbol_from_moat_config(tmp_path: Path):
    moat_path = tmp_path / "moat_static_base.yaml"
    moat_path.write_text(
        yaml.safe_dump(
            {
                "companies": {
                    "600519": {
                        "name": "贵州茅台",
                        "sector": "白酒",
                        "theme": "Consumer_Staples",
                        "ecosystem_role": "downstream_app",
                        "fund_heavy_holding_count": 1352,
                    }
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    target = TargetResolver(moat_path).resolve(
        symbol="600519",
        market=Market.A_SHARE,
        asset_class="equity",
    )

    assert target.symbol == "600519"
    assert target.name == "贵州茅台"
    assert target.sector == "白酒"
    assert target.theme == "Consumer_Staples"
    assert target.ecosystem_role == "downstream_app"
    assert target.fund_heavy_holding_count == 1352


def test_target_resolver_keeps_explicit_overrides_when_present(tmp_path: Path):
    moat_path = tmp_path / "moat_static_base.yaml"
    moat_path.write_text(
        yaml.safe_dump(
            {
                "companies": {
                    "600519": {
                        "name": "贵州茅台",
                        "sector": "白酒",
                        "theme": "Consumer_Staples",
                        "ecosystem_role": "downstream_app",
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    target = TargetResolver(moat_path).resolve(
        symbol="600519",
        market=Market.A_SHARE,
        asset_class="equity",
        sector="食品饮料",
    )

    assert target.sector == "食品饮料"
    assert target.theme == "Consumer_Staples"


def test_target_resolver_returns_minimal_target_for_unknown_symbol(tmp_path: Path):
    moat_path = tmp_path / "moat_static_base.yaml"
    moat_path.write_text("companies: {}\n", encoding="utf-8")

    target = TargetResolver(moat_path).resolve(
        symbol="UNKNOWN",
        market=Market.A_SHARE,
        asset_class="equity",
    )

    assert target.symbol == "UNKNOWN"
    assert target.name is None
    assert target.sector is None
    assert target.theme is None
    assert target.ecosystem_role is None

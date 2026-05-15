import pytest
from pathlib import Path
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.policy import PolicyFactorPlugin
from sentinel.domain.models import Market


def test_symbiotic_infra_gets_premium_in_hot_theme(tmp_path):
    policy_yaml = tmp_path / "policy_whitelist.yaml"
    policy_yaml.write_text("version: '1.0'\ndefault_multiplier: 1.0\nsectors: {}\noverrides: {}")

    ecosystem_yaml = tmp_path / "ecosystem_themes.yaml"
    ecosystem_yaml.write_text("""
version: "1.0"
hot_themes:
  - "AI_Compute_Infrastructure"
role_premiums:
  symbiotic_infra: 0.10
  core_arena: -0.05
  upstream_resource: 0.0
  downstream_app: 0.0
""")

    plugin = PolicyFactorPlugin(
        config_path=policy_yaml,
        ecosystem_config_path=ecosystem_yaml,
    )
    target = TargetInfo(
        symbol="600900",
        market=Market.A_SHARE,
        asset_class="equity",
        theme="AI_Compute_Infrastructure",
        ecosystem_role="symbiotic_infra",
    )
    score = plugin.evaluate(target)

    assert score.details["multiplier"] == pytest.approx(1.10, abs=0.001)
    assert score.details["ecosystem_premium"] == pytest.approx(0.10, abs=0.001)
    assert "生态红利" in score.details["note"]


def test_core_arena_gets_no_premium_outside_hot_theme(tmp_path):
    policy_yaml = tmp_path / "policy_whitelist.yaml"
    policy_yaml.write_text("version: '1.0'\ndefault_multiplier: 1.0")

    ecosystem_yaml = tmp_path / "ecosystem_themes.yaml"
    ecosystem_yaml.write_text("""
version: "1.0"
hot_themes:
  - "AI_Compute_Infrastructure"
role_premiums:
  symbiotic_infra: 0.10
""")

    plugin = PolicyFactorPlugin(
        config_path=policy_yaml,
        ecosystem_config_path=ecosystem_yaml,
    )
    target = TargetInfo(
        symbol="300001",
        market=Market.A_SHARE,
        asset_class="equity",
        theme="Some_Other_Theme",
        ecosystem_role="symbiotic_infra",
    )
    score = plugin.evaluate(target)

    assert score.details["multiplier"] == pytest.approx(1.0, abs=0.001)
    assert score.details.get("ecosystem_premium", 0) == 0.0

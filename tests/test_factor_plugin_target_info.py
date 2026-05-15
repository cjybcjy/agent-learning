from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.domain.models import Market


def test_target_info_accepts_theme_and_ecosystem_role():
    t = TargetInfo(
        symbol="600900",
        market=Market.A_SHARE,
        asset_class="equity",
        name="长江电力",
        sector="电力",
        theme="AI_Compute_Infrastructure",
        ecosystem_role="symbiotic_infra",
    )
    assert t.theme == "AI_Compute_Infrastructure"
    assert t.ecosystem_role == "symbiotic_infra"

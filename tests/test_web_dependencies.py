from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.web import dependencies


def test_get_orchestrator_injects_metrics_aggregator_into_moat_plugin(
    monkeypatch, settings
):
    (settings.config_dir / "mgfs_config.yaml").write_text(
        """
version: "1.0"
modules:
  moat:
    enabled: true
    class_path: "sentinel.mgfs.plugins.moat.MoatFactorPlugin"
    config: {}
scoring_formula:
  moat: { weight: 1.0 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
circuit_breakers: {}
rating_thresholds:
  avoid: { min_score: 0.0, label: "Avoid", action: "avoid" }
""",
        encoding="utf-8",
    )
    (settings.config_dir / "moat_static_base.yaml").write_text(
        "version: '1.0'\ncompanies: {}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("sentinel.config.AppSettings", lambda: settings)
    dependencies._orchestrator = None
    dependencies._scanner = None

    orchestrator = dependencies.get_orchestrator()

    moat_plugin = orchestrator.plugins["moat"]
    assert isinstance(moat_plugin.aggregator, MetricsAggregator)
    assert moat_plugin.aggregator.database.path == settings.database_path

    dependencies._orchestrator = None
    dependencies._scanner = None

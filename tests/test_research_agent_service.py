from pathlib import Path

import json
import yaml

from sentinel.web.services.research_agent_service import ResearchAgentService


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_daily_review_flags_stale_configs_and_theme_concentration(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(
        config_dir / "policy_whitelist.yaml",
        {
            "last_updated": "2026-05-01",
            "sectors": {"半导体": {"multiplier": 1.2}},
        },
    )
    _write_yaml(
        config_dir / "ecosystem_themes.yaml",
        {
            "hot_themes": ["AI_Compute_Infrastructure"],
            "role_premiums": {"core_arena": -0.05},
        },
    )
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {
            "last_updated": "2026-05-01",
            "companies": {
                "000001": {
                    "theme": "AI_Compute_Infrastructure",
                    "sector": "银行",
                    "base_score": {},
                },
                "000002": {
                    "theme": "AI_Compute_Infrastructure",
                    "sector": "地产",
                    "base_score": {},
                },
                "000003": {
                    "theme": "Consumer_Staples",
                    "sector": "食品饮料",
                    "base_score": {},
                },
            },
        },
    )

    service = ResearchAgentService(
        config_dir=config_dir,
        store_path=tmp_path / "agent_runs.json",
        today="2026-06-17",
    )
    run = service.run_daily_review()

    titles = [item.title for item in run.suggestions]
    assert "政策白名单需要复核" in titles
    assert "主题覆盖过于集中" in titles
    assert "生态主题缺少反向观察池" in titles
    assert run.mode == "read_only_advisory"
    assert run.source_mix["internal_config"] >= 3
    assert all(item.counter_evidence for item in run.suggestions)


def test_daily_review_persists_latest_run_and_status_without_editing_config(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    moat_path = config_dir / "moat_static_base.yaml"
    original_moat = {
        "last_updated": "2026-05-01",
        "companies": {
            "000001": {
                "theme": "AI",
                "sector": "银行",
                "base_score": {},
            }
        },
    }
    _write_yaml(moat_path, original_moat)
    _write_yaml(
        config_dir / "policy_whitelist.yaml",
        {"last_updated": "2026-05-01", "sectors": {}},
    )
    _write_yaml(
        config_dir / "ecosystem_themes.yaml",
        {"hot_themes": ["AI"], "role_premiums": {}},
    )

    service = ResearchAgentService(
        config_dir=config_dir,
        store_path=tmp_path / "agent_runs.json",
        today="2026-06-17",
    )
    run = service.run_daily_review()
    updated = service.update_suggestion_status(run.suggestions[0].id, "watching")

    latest = service.load_latest_run()
    assert latest is not None
    assert updated.status == "watching"
    assert any(item.status == "watching" for item in latest.suggestions)
    assert yaml.safe_load(moat_path.read_text(encoding="utf-8")) == original_moat


def test_daily_review_flags_moat_scores_without_evidence_fields(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(
        config_dir / "policy_whitelist.yaml",
        {"last_updated": "2026-06-10", "sectors": {}},
    )
    _write_yaml(
        config_dir / "ecosystem_themes.yaml",
        {
            "last_updated": "2026-06-10",
            "hot_themes": ["Consumer_Staples"],
            "negative_watchlist": [],
        },
    )
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {
            "last_updated": "2026-06-10",
            "companies": {
                "600519": {
                    "theme": "Consumer_Staples",
                    "sector": "白酒",
                    "base_score": {
                        "brand_premium": {
                            "score": 95,
                            "note": "高端白酒定价权",
                        }
                    },
                }
            },
        },
    )

    service = ResearchAgentService(
        config_dir=config_dir,
        store_path=tmp_path / "agent_runs.json",
        today="2026-06-17",
    )
    run = service.run_daily_review()

    suggestion = next(
        item for item in run.suggestions
        if item.title == "护城河评分缺少证据字段"
    )
    assert suggestion.category == "证据覆盖"
    assert suggestion.config_file == "moat_static_base.yaml"
    assert "覆盖率 0%" in suggestion.rationale
    assert "source/as_of/confidence/bear_case" in suggestion.proposed_change
    assert suggestion.evidence
    assert suggestion.counter_evidence


def test_daily_review_uses_external_signal_snapshot_for_policy_and_moat(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(
        config_dir / "policy_whitelist.yaml",
        {
            "last_updated": "2026-06-20",
            "sectors": {"人工智能": {"multiplier": 1.2}},
        },
    )
    _write_yaml(
        config_dir / "ecosystem_themes.yaml",
        {
            "last_updated": "2026-06-20",
            "hot_themes": ["AI_Compute_Infrastructure"],
            "negative_watchlist": [],
        },
    )
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {
            "last_updated": "2026-06-20",
            "companies": {
                "300750": {
                    "name": "宁德时代",
                    "sector": "新能源汽车",
                    "theme": "Smart_EV_Supply_Chain",
                    "base_score": {},
                }
            },
        },
    )
    signal_path = tmp_path / "research_external_signals.json"
    signal_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-23T08:00:00",
                "items": [
                    {
                        "category": "policy",
                        "source": "国务院政策例行吹风会",
                        "title": "人工智能+行动持续推进",
                        "published_at": "2026-06-22",
                        "sectors": ["人工智能"],
                        "themes": ["AI_Compute_Infrastructure"],
                        "url": "https://example.com/policy-ai",
                        "polarity": "supporting",
                        "impact": "高",
                    },
                    {
                        "category": "moat",
                        "source": "交易所公告",
                        "title": "宁德时代海外订单结构变化",
                        "published_at": "2026-06-21",
                        "symbols": ["300750"],
                        "url": "https://example.com/300750",
                        "polarity": "counter",
                        "impact": "中",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service = ResearchAgentService(
        config_dir=config_dir,
        store_path=tmp_path / "agent_runs.json",
        external_signal_path=signal_path,
        today="2026-06-23",
    )

    run = service.run_daily_review()

    titles = [item.title for item in run.suggestions]
    assert "政策白名单有新外部信号待复核" in titles
    assert "护城河外部信号待复核" in titles
    assert run.source_mix["external_news"] == 2
    policy_suggestion = next(
        item for item in run.suggestions
        if item.title == "政策白名单有新外部信号待复核"
    )
    assert policy_suggestion.config_file == "policy_whitelist.yaml"
    assert "国务院政策例行吹风会" in policy_suggestion.evidence[0].source
    assert "https://example.com/policy-ai" in policy_suggestion.evidence[0].detail
    moat_suggestion = next(
        item for item in run.suggestions
        if item.title == "护城河外部信号待复核"
    )
    assert moat_suggestion.target == "宁德时代(300750)"
    assert moat_suggestion.counter_evidence


def test_ensure_daily_review_runs_once_per_day(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(config_dir / "policy_whitelist.yaml", {"last_updated": "2026-06-20"})
    _write_yaml(
        config_dir / "ecosystem_themes.yaml",
        {"last_updated": "2026-06-20", "negative_watchlist": []},
    )
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {"last_updated": "2026-06-20", "companies": {}},
    )
    service = ResearchAgentService(
        config_dir=config_dir,
        store_path=tmp_path / "agent_runs.json",
        today="2026-06-23",
    )

    first = service.ensure_daily_review()
    second = service.ensure_daily_review()

    payload = json.loads((tmp_path / "agent_runs.json").read_text(encoding="utf-8"))
    assert first.run_id == second.run_id
    assert len(payload["runs"]) == 1

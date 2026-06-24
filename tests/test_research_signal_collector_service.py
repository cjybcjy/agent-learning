from __future__ import annotations

import json
from pathlib import Path

import yaml

from sentinel.web.services.research_signal_collector_service import (
    ResearchSignalCollectorService,
)


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_collector_builds_policy_and_moat_snapshot_from_configured_sources(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {
            "companies": {
                "300750": {
                    "name": "宁德时代",
                    "sector": "新能源汽车",
                    "theme": "Smart_EV_Supply_Chain",
                }
            }
        },
    )
    _write_yaml(
        config_dir / "research_signal_sources.yaml",
        {
            "sources": [
                {
                    "key": "policy_feed",
                    "enabled": True,
                    "kind": "rss",
                    "category": "policy",
                    "name": "官方政策RSS",
                    "url": "https://example.test/policy.xml",
                    "require_keyword_match": True,
                    "keyword_rules": [
                        {
                            "contains": ["人工智能+"],
                            "sectors": ["人工智能"],
                            "themes": ["AI_Compute_Infrastructure"],
                            "impact": "高",
                        }
                    ],
                },
                {
                    "key": "cninfo",
                    "enabled": True,
                    "kind": "json",
                    "category": "moat",
                    "name": "巨潮公告",
                    "url": "https://example.test/cninfo.json",
                    "items_path": "announcements",
                    "fields": {
                        "title": "announcementTitle",
                        "url": "pdfUrl",
                        "published_at": "announcementTime",
                        "symbol": "secCode",
                    },
                },
            ]
        },
    )

    responses = {
        "https://example.test/policy.xml": """
<rss><channel>
  <item>
    <title>人工智能+行动持续推进</title>
    <link>https://example.test/policy-ai</link>
    <pubDate>2026-06-22</pubDate>
    <description>推动智能经济新形态</description>
  </item>
  <item>
    <title>无关行政批复</title>
    <link>https://example.test/other</link>
    <pubDate>2026-06-22</pubDate>
    <description>不应进入投研信号</description>
  </item>
</channel></rss>
""",
        "https://example.test/cninfo.json": json.dumps(
            {
                "announcements": [
                    {
                        "secCode": "300750",
                        "secName": "宁德时代",
                        "announcementTitle": "关于海外客户订单结构变化的公告",
                        "announcementTime": "2026-06-21",
                        "pdfUrl": "https://example.test/300750.pdf",
                    },
                    {
                        "secCode": "300750",
                        "secName": "宁德时代",
                        "announcementTitle": "关于海外客户订单结构变化的公告",
                        "announcementTime": "2026-06-21",
                        "pdfUrl": "https://example.test/300750.pdf",
                    },
                ]
            },
            ensure_ascii=False,
        ),
    }

    service = ResearchSignalCollectorService(
        config_dir=config_dir,
        output_path=tmp_path / "research_external_signals.json",
        fetch_text=lambda url: responses[url],
        today="2026-06-23",
    )

    snapshot = service.collect()

    assert snapshot["generated_at"].startswith("2026-06-23T")
    assert snapshot["source_count"] == 2
    assert len(snapshot["items"]) == 2
    policy = next(item for item in snapshot["items"] if item["category"] == "policy")
    assert policy["source"] == "官方政策RSS"
    assert policy["sectors"] == ["人工智能"]
    assert policy["themes"] == ["AI_Compute_Infrastructure"]
    assert policy["impact"] == "高"
    moat = next(item for item in snapshot["items"] if item["category"] == "moat")
    assert moat["source"] == "巨潮公告"
    assert moat["symbols"] == ["300750"]
    assert moat["url"] == "https://example.test/300750.pdf"

    persisted = json.loads(
        (tmp_path / "research_external_signals.json").read_text(encoding="utf-8")
    )
    assert persisted == snapshot


def test_collector_ensure_daily_snapshot_reuses_today_output(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(config_dir / "research_signal_sources.yaml", {"sources": []})
    output_path = tmp_path / "research_external_signals.json"
    output_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-23T08:00:00",
                "source_count": 0,
                "items": [{"title": "existing"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls = {"fetch": 0}

    service = ResearchSignalCollectorService(
        config_dir=config_dir,
        output_path=output_path,
        fetch_text=lambda url: calls.__setitem__("fetch", calls["fetch"] + 1) or "",
        today="2026-06-23",
    )

    snapshot = service.ensure_daily_snapshot()

    assert snapshot["items"] == [{"title": "existing"}]
    assert calls["fetch"] == 0

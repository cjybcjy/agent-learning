from pathlib import Path
from types import SimpleNamespace

import yaml

from sentinel.web.services.candidate_discovery_service import (
    AkshareBoardProvider,
    CandidateDiscoveryService,
)


class FakeBoardProvider:
    def list_concept_boards(self) -> list[dict]:
        return [
            {"排名": 1, "板块名称": "机器人概念", "板块代码": "BK0001"},
            {"排名": 2, "板块名称": "减速器", "板块代码": "BK0002"},
            {"排名": 3, "板块名称": "白酒概念", "板块代码": "BK0003"},
        ]

    def list_industry_boards(self) -> list[dict]:
        return [
            {"排名": 1, "板块名称": "自动化设备", "板块代码": "BK1001"},
            {"排名": 2, "板块名称": "机器人执行器", "板块代码": "BK1002"},
        ]

    def board_constituents(self, source: str, board_name: str) -> list[dict]:
        rows = {
            "机器人概念": [
                {"代码": "300024", "名称": "机器人"},
                {"代码": "002747", "名称": "埃斯顿"},
            ],
            "减速器": [
                {"代码": "688017", "名称": "绿的谐波"},
                {"代码": "300024", "名称": "机器人"},
            ],
            "机器人执行器": [
                {"代码": "002050", "名称": "三花智控"},
                {"代码": "300024", "名称": "机器人"},
            ],
        }
        return rows.get(board_name, [])


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_candidate_discovery_uses_board_membership_evidence(tmp_path: Path):
    _write_yaml(
        tmp_path / "ecosystem_themes.yaml",
        {
            "macro_themes": [
                {
                    "key": "Embodied_Robotics",
                    "label": "机器人与具身智能",
                    "a_share_chain": ["减速器", "执行器"],
                }
            ]
        },
    )
    _write_yaml(
        tmp_path / "moat_static_base.yaml",
        {
            "companies": {
                "300024": {
                    "name": "机器人",
                    "theme": "Embodied_Robotics",
                    "fund_heavy_holding_count": 11,
                }
            }
        },
    )

    service = CandidateDiscoveryService(
        config_dir=tmp_path,
        provider=FakeBoardProvider(),
        max_candidates=10,
    )
    result = service.discover_theme("Embodied_Robotics")

    assert result.theme_label == "机器人与具身智能"
    assert result.matched_board_count == 3
    assert result.source_mix == {"concept": 2, "industry": 1}
    assert [candidate.symbol for candidate in result.candidates][:2] == [
        "300024",
        "002050",
    ]
    top = result.candidates[0]
    assert top.evidence_count == 3
    assert top.in_static_pool is True
    assert top.fund_heavy_holding_count == 11
    assert result.candidates[1].in_static_pool is False


def test_candidate_discovery_reports_unknown_theme(tmp_path: Path):
    _write_yaml(tmp_path / "ecosystem_themes.yaml", {"macro_themes": []})

    service = CandidateDiscoveryService(
        config_dir=tmp_path,
        provider=FakeBoardProvider(),
    )
    result = service.discover_theme("Missing")

    assert result.candidates == []
    assert result.warnings == ["未找到主题配置: Missing"]


def test_akshare_provider_falls_back_to_ths_concept_names(monkeypatch):
    fake_akshare = SimpleNamespace(
        stock_board_concept_name_em=lambda: (_ for _ in ()).throw(RuntimeError("proxy down")),
        stock_board_concept_name_ths=lambda: [
            {"name": "机器人概念", "code": "300816"},
            {"name": "减速器", "code": "309000"},
        ],
    )
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_akshare)

    boards = AkshareBoardProvider().list_concept_boards()

    assert boards == [
        {"板块名称": "机器人概念", "板块代码": "300816"},
        {"板块名称": "减速器", "板块代码": "309000"},
    ]


def test_akshare_provider_falls_back_to_ths_industry_names(monkeypatch):
    fake_akshare = SimpleNamespace(
        stock_board_industry_name_em=lambda: (_ for _ in ()).throw(RuntimeError("proxy down")),
        stock_board_industry_name_ths=lambda: [
            {"name": "半导体", "code": "881121"},
            {"name": "电机", "code": "881277"},
        ],
    )
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_akshare)

    boards = AkshareBoardProvider().list_industry_boards()

    assert boards == [
        {"板块名称": "半导体", "板块代码": "881121"},
        {"板块名称": "电机", "板块代码": "881277"},
    ]

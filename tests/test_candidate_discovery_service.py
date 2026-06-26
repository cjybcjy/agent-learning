from pathlib import Path
from types import SimpleNamespace

import yaml

from sentinel.web.services.candidate_discovery_service import (
    AkshareBoardProvider,
    CandidateDiscoveryService,
)
import sentinel.web.services.candidate_discovery_service as candidate_module


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

    def board_constituents(
        self,
        source: str,
        board_name: str,
        board_code: str | None = None,
    ) -> list[dict]:
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


def test_candidate_discovery_passes_board_code_to_constituent_provider(
    tmp_path: Path,
):
    _write_yaml(
        tmp_path / "ecosystem_themes.yaml",
        {
            "macro_themes": [
                {
                    "key": "Custom_Theme",
                    "label": "自定义主题",
                    "a_share_chain": ["定制板块"],
                }
            ]
        },
    )
    _write_yaml(tmp_path / "moat_static_base.yaml", {"companies": {}})
    seen_codes: list[str | None] = []

    class CodeAwareProvider:
        def list_concept_boards(self) -> list[dict]:
            return [{"排名": 1, "板块名称": "定制板块", "板块代码": "BK9999"}]

        def list_industry_boards(self) -> list[dict]:
            return []

        def board_constituents(
            self,
            source: str,
            board_name: str,
            board_code: str | None = None,
        ) -> list[dict]:
            seen_codes.append(board_code)
            return [{"代码": "300065", "名称": "海兰信"}]

    service = CandidateDiscoveryService(
        config_dir=tmp_path,
        provider=CodeAwareProvider(),
    )

    result = service.discover_theme("Custom_Theme")

    assert seen_codes == ["BK9999"]
    assert [candidate.symbol for candidate in result.candidates] == ["300065"]


def test_candidate_discovery_uses_builtin_low_altitude_board_fallback(
    tmp_path: Path,
):
    _write_yaml(
        tmp_path / "ecosystem_themes.yaml",
        {
            "macro_themes": [
                {
                    "key": "Low_Altitude_Economy",
                    "label": "低空经济",
                    "a_share_chain": ["eVTOL", "无人机"],
                }
            ]
        },
    )
    _write_yaml(tmp_path / "moat_static_base.yaml", {"companies": {}})

    class NoListProvider:
        def list_concept_boards(self) -> list[dict]:
            raise AssertionError("fallback should avoid full concept list")

        def list_industry_boards(self) -> list[dict]:
            return []

        def board_constituents(
            self,
            source: str,
            board_name: str,
            board_code: str | None = None,
        ) -> list[dict]:
            code_by_board = {
                "低空经济": "301001",
                "飞行汽车(eVTOL)": "301002",
                "无人机": "301003",
            }
            return [
                {
                    "代码": code_by_board[board_name],
                    "名称": f"{board_name}候选",
                }
            ]

    service = CandidateDiscoveryService(
        config_dir=tmp_path,
        provider=NoListProvider(),
    )

    result = service.discover_theme("Low_Altitude_Economy")

    assert result.matched_board_count == 3
    assert result.source_mix["concept"] == 3
    assert {item.name for item in result.candidates} == {
        "低空经济候选",
        "飞行汽车(eVTOL)候选",
        "无人机候选",
    }
    assert not result.warnings


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
    monkeypatch.setattr(
        candidate_module,
        "_fetch_eastmoney_board_list",
        lambda source: (_ for _ in ()).throw(RuntimeError("direct eastmoney down")),
    )
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


def test_akshare_provider_prefers_direct_eastmoney_concept_boards(monkeypatch):
    monkeypatch.setattr(
        candidate_module,
        "_fetch_eastmoney_board_list",
        lambda source: [{"板块名称": "低空经济", "板块代码": "BK0715"}],
    )
    fake_akshare = SimpleNamespace(
        stock_board_concept_name_em=lambda: (_ for _ in ()).throw(
            AssertionError("akshare should not be called")
        ),
        stock_board_concept_name_ths=lambda: (_ for _ in ()).throw(
            AssertionError("ths fallback should not be called")
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_akshare)

    boards = AkshareBoardProvider().list_concept_boards()

    assert boards == [{"板块名称": "低空经济", "板块代码": "BK0715"}]


def test_akshare_provider_falls_back_to_direct_eastmoney_constituents(monkeypatch):
    fake_akshare = SimpleNamespace(
        stock_board_concept_cons_em=lambda symbol: (_ for _ in ()).throw(
            RuntimeError("akshare proxy down")
        )
    )
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_akshare)
    monkeypatch.setattr(
        candidate_module,
        "_fetch_eastmoney_board_constituents",
        lambda board_code: [
            {"代码": "300065", "名称": "海兰信"},
            {"代码": "002167", "名称": "东方锆业"},
        ],
    )

    rows = AkshareBoardProvider().board_constituents(
        "concept",
        "低空经济",
        board_code="BK0715",
    )

    assert rows == [
        {"代码": "300065", "名称": "海兰信"},
        {"代码": "002167", "名称": "东方锆业"},
    ]


def test_akshare_provider_resolves_board_name_to_eastmoney_code(monkeypatch):
    fake_akshare = SimpleNamespace(
        stock_board_concept_cons_em=lambda symbol: (_ for _ in ()).throw(
            RuntimeError("akshare proxy down")
        )
    )
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_akshare)
    monkeypatch.setattr(
        candidate_module,
        "_resolve_eastmoney_board_code",
        lambda board_name: "BK1166" if board_name == "低空经济" else None,
    )

    seen_codes = []

    def fake_constituents(board_code: str) -> list[dict]:
        seen_codes.append(board_code)
        return [{"代码": "300065", "名称": "海兰信"}]

    monkeypatch.setattr(
        candidate_module,
        "_fetch_eastmoney_board_constituents",
        fake_constituents,
    )

    rows = AkshareBoardProvider().board_constituents(
        "concept",
        "低空经济",
        board_code=None,
    )

    assert seen_codes == ["BK1166"]
    assert rows == [{"代码": "300065", "名称": "海兰信"}]


def test_akshare_provider_falls_back_to_ths_constituents_for_ths_code(monkeypatch):
    fake_akshare = SimpleNamespace(
        stock_board_concept_cons_em=lambda symbol: (_ for _ in ()).throw(
            RuntimeError("akshare proxy down")
        )
    )
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_akshare)
    monkeypatch.setattr(candidate_module, "_resolve_eastmoney_board_code", lambda _: None)
    monkeypatch.setattr(candidate_module, "_fetch_eastmoney_board_constituents", lambda _: [])
    monkeypatch.setattr(
        candidate_module,
        "_fetch_ths_concept_constituents",
        lambda ths_code: [{"代码": "301366", "名称": "一博科技"}],
    )

    rows = AkshareBoardProvider().board_constituents(
        "concept",
        "低空经济",
        board_code="309115",
    )

    assert rows == [{"代码": "301366", "名称": "一博科技"}]


def test_akshare_provider_falls_back_to_ths_industry_names(monkeypatch):
    monkeypatch.setattr(
        candidate_module,
        "_fetch_eastmoney_board_list",
        lambda source: (_ for _ in ()).throw(RuntimeError("direct eastmoney down")),
    )
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

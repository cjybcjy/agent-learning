from datetime import datetime

from fastapi.testclient import TestClient

from sentinel.web.main import create_app
from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import AlertLevel, FactorScore, TargetInfo
from sentinel.mgfs.orchestrator import InvestmentDecision
from sentinel.mgfs.target_resolver import TargetResolver
from sentinel.web.services.eval_service import evaluate_single


def test_eval_single_returns_decision_card():
    client = TestClient(create_app())
    response = client.post("/api/eval/single", data={"symbol": "600519", "market": "A_SHARE"})
    assert response.status_code == 200
    assert "600519" in response.text
    assert "护城河" in response.text


def test_decision_card_shows_technical_signal_panel(monkeypatch):
    target = TargetInfo(
        symbol="600519",
        market=Market.A_SHARE,
        asset_class="equity",
        name="贵州茅台",
        sector="白酒",
    )
    decision = InvestmentDecision(
        target=target,
        generated_at=datetime.now(),
        factor_scores={
            "timing": FactorScore(
                factor_key="timing",
                factor_name="量化择时",
                score=82.0,
                confidence=0.8,
                details={
                    "technical_signal": {
                        "entry_label": "entry_watch",
                        "entry_tags": ["pullback_recovery"],
                        "exit_label": "none",
                        "exit_tags": [],
                        "ma60": 112.41,
                        "bias60": -0.0054,
                        "ma60_slope20": 0.0189,
                        "rsi14": 44.02,
                        "volume_ratio20": 1.73,
                        "entry_zone_low": 108.3,
                        "entry_zone_high": 114.47,
                        "stop_reference": 107.86,
                        "instruction_boundary": "research_only",
                    }
                },
            )
        },
        raw_total=82.0,
        policy_multiplier=1.0,
        final_score=82.0,
        rating="Accumulate",
        action="继续观察",
        circuit_breakers_triggered=[],
        alert_level=AlertLevel.GREEN_PASS,
        report_sections={"overall_confidence": 0.8},
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.evaluate_single",
        lambda **kwargs: decision,
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.build_moat_radar_data",
        lambda symbol: None,
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.build_valuation_band_data",
        lambda **kwargs: None,
    )

    response = TestClient(create_app()).post(
        "/api/eval/single",
        data={"symbol": "600519", "market": "A_SHARE"},
    )

    assert response.status_code == 200
    assert "技术信号" in response.text
    assert "回踩修复" in response.text
    assert "仅供研究" in response.text
    assert 'hx-post="/api/serenity-verification-plan"' in response.text
    assert "补证据路线" in response.text


def test_decision_card_explains_data_watermark_reasons(monkeypatch):
    target = TargetInfo(
        symbol="600519",
        market=Market.A_SHARE,
        asset_class="equity",
        name="贵州茅台",
        sector="白酒",
    )
    decision = InvestmentDecision(
        target=target,
        generated_at=datetime.now(),
        factor_scores={
            "timing": FactorScore(
                factor_key="timing",
                factor_name="量化择时",
                score=66.0,
                confidence=0.65,
                details={
                    "sample_size": 120,
                    "requested_days": 520,
                    "confidence_tier": "short_sample",
                },
                warnings=["样本窗口未达请求: 120/520 根K线，择时置信度按实际样本降级"],
            ),
            "moat": FactorScore(
                factor_key="moat",
                factor_name="护城河",
                score=82.0,
                confidence=0.5,
                warnings=["动态指标数据缺失，仅使用静态评分"],
            ),
        },
        raw_total=72.0,
        policy_multiplier=1.0,
        final_score=72.0,
        rating="Hold/Watch",
        action="等待拐点",
        circuit_breakers_triggered=[],
        alert_level=AlertLevel.YELLOW_WARNING,
        report_sections={
            "overall_confidence": 0.72,
            "watermark": "[数据部分缺失]",
            "inactive_weight": 0.2,
        },
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.evaluate_single",
        lambda **kwargs: decision,
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.build_moat_radar_data",
        lambda symbol: None,
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.build_valuation_band_data",
        lambda **kwargs: None,
    )

    response = TestClient(create_app()).post(
        "/api/eval/single",
        data={"symbol": "600519", "market": "A_SHARE"},
    )

    assert response.status_code == 200
    assert "缺失原因" in response.text
    assert "总体置信度" in response.text
    assert "72%" in response.text
    assert "量化择时" in response.text
    assert "样本窗口" in response.text
    assert "120/520" in response.text
    assert "护城河" in response.text
    assert "动态指标数据缺失，仅使用静态评分" in response.text


def test_decision_card_groups_timing_warning_with_technical_signal(monkeypatch):
    target = TargetInfo(
        symbol="600519",
        market=Market.A_SHARE,
        asset_class="equity",
        name="贵州茅台",
        sector="白酒",
    )
    timing_warning = "60日均线斜率 -3.77%（阈值 -3.00%），触发择时一票否决"
    decision = InvestmentDecision(
        target=target,
        generated_at=datetime.now(),
        factor_scores={
            "timing": FactorScore(
                factor_key="timing",
                factor_name="量化择时",
                score=0.0,
                confidence=0.85,
                details={
                    "sample_size": 520,
                    "requested_days": 520,
                    "confidence_tier": "two_year",
                    "technical_signal": {
                        "entry_label": "none",
                        "entry_tags": [],
                        "exit_label": "exit_risk",
                        "exit_tags": ["trend_breakdown"],
                        "ma60": 1356.02,
                        "bias60": -0.0985,
                        "ma60_slope20": -0.0377,
                        "rsi14": 30.7,
                        "volume_ratio20": 1.28,
                        "entry_zone_low": 1304.89,
                        "entry_zone_high": 1381.58,
                        "stop_reference": 1304.81,
                        "instruction_boundary": "research_only",
                    },
                },
                warnings=[timing_warning],
            ),
            "moat": FactorScore(
                factor_key="moat",
                factor_name="护城河",
                score=82.0,
                confidence=0.5,
                warnings=["动态指标数据缺失，仅使用静态评分"],
            ),
        },
        raw_total=42.0,
        policy_multiplier=1.0,
        final_score=42.0,
        rating="Avoid",
        action="等待拐点",
        circuit_breakers_triggered=[],
        alert_level=AlertLevel.YELLOW_WARNING,
        report_sections={
            "overall_confidence": 0.55,
            "watermark": "[数据部分缺失]",
        },
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.evaluate_single",
        lambda **kwargs: decision,
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.build_moat_radar_data",
        lambda symbol: None,
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.build_valuation_band_data",
        lambda **kwargs: None,
    )

    response = TestClient(create_app()).post(
        "/api/eval/single",
        data={"symbol": "600519", "market": "A_SHARE"},
    )

    assert response.status_code == 200
    technical_panel = response.text.split('data-testid="technical-signal-panel"', 1)[1].split(
        'data-testid="data-gap-reasons"', 1
    )[0]
    data_gap_panel = response.text.split('data-testid="data-gap-reasons"', 1)[1]
    assert "择时风险" in technical_panel
    assert "趋势破位" in technical_panel
    assert timing_warning in technical_panel
    assert timing_warning not in data_gap_panel


def test_decision_card_shows_judgment_logic_ticket(monkeypatch):
    target = TargetInfo(
        symbol="600519",
        market=Market.A_SHARE,
        asset_class="equity",
        name="贵州茅台",
        sector="白酒",
    )
    decision = InvestmentDecision(
        target=target,
        generated_at=datetime.now(),
        factor_scores={
            "moat": FactorScore(
                factor_key="moat",
                factor_name="护城河",
                score=82.0,
                confidence=0.72,
                details={"trend_score": 78.0, "safety_score": 70.0},
                warnings=["动态指标数据缺失，仅使用静态评分"],
            ),
            "valuation": FactorScore(
                factor_key="valuation",
                factor_name="估值",
                score=68.0,
                confidence=0.8,
            ),
            "policy": FactorScore(
                factor_key="policy",
                factor_name="政策传导",
                score=80.0,
                confidence=0.85,
                details={"policy_rating": "core_support", "multiplier": 1.15},
            ),
            "timing": FactorScore(
                factor_key="timing",
                factor_name="量化择时",
                score=55.0,
                confidence=0.75,
                details={
                    "technical_signal": {
                        "entry_label": "none",
                        "entry_tags": [],
                        "exit_label": "none",
                        "exit_tags": [],
                        "ma60": 1356.02,
                        "bias60": -0.02,
                        "ma60_slope20": 0.01,
                        "rsi14": 48.0,
                        "volume_ratio20": 1.05,
                        "entry_zone_low": 1320.0,
                        "entry_zone_high": 1380.0,
                        "stop_reference": 1300.0,
                        "instruction_boundary": "research_only",
                    }
                },
            ),
        },
        raw_total=70.0,
        policy_multiplier=1.15,
        final_score=80.5,
        rating="Accumulate",
        action="继续观察",
        circuit_breakers_triggered=[],
        alert_level=AlertLevel.YELLOW_WARNING,
        report_sections={
            "overall_confidence": 0.76,
            "watermark": "[数据部分缺失]",
            "effective_policy_rating": "core_support",
        },
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.evaluate_single",
        lambda **kwargs: decision,
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.build_moat_radar_data",
        lambda symbol: None,
    )
    monkeypatch.setattr(
        "sentinel.web.routers.research.build_valuation_band_data",
        lambda **kwargs: None,
    )

    response = TestClient(create_app()).post(
        "/api/eval/single",
        data={"symbol": "600519", "market": "A_SHARE"},
    )

    assert response.status_code == 200
    assert 'data-testid="judgment-ticket"' in response.text
    assert "判断逻辑票据" in response.text
    assert "风险闸门" in response.text
    assert "盈利能力" in response.text
    assert "财务安全" in response.text
    assert "政策传导" in response.text
    assert "技术趋势" in response.text
    assert "总分" in response.text
    assert "最不放心" in response.text
    assert 'hx-post="/api/research-data/fill-gaps"' in response.text
    assert "执行补数据" in response.text
    assert "巨潮风险公告核验" in response.text
    assert 'name="task_keys"' in response.text


def test_evaluate_single_uses_target_resolver_metadata(tmp_path, monkeypatch):
    moat_path = tmp_path / "moat_static_base.yaml"
    moat_path.write_text(
        """
companies:
  "600519":
    name: "贵州茅台"
    sector: "白酒"
    theme: "Consumer_Staples"
    ecosystem_role: "downstream_app"
""",
        encoding="utf-8",
    )
    captured: dict[str, TargetInfo] = {}

    class FakeOrchestrator:
        def evaluate(self, target: TargetInfo, policy_rating: str = "neutral"):
            captured["target"] = target
            return InvestmentDecision(
                target=target,
                generated_at=datetime.now(),
                factor_scores={},
                raw_total=0.0,
                policy_multiplier=1.0,
                final_score=0.0,
                rating="Avoid",
                action="回避",
                circuit_breakers_triggered=[],
                alert_level=AlertLevel.GREEN_PASS,
            )

    monkeypatch.setattr("sentinel.web.services.eval_service.get_orchestrator", lambda: FakeOrchestrator())

    evaluate_single(
        symbol="600519",
        market="A_SHARE",
        target_resolver=TargetResolver(moat_path),
    )

    target = captured["target"]
    assert target.market == Market.A_SHARE
    assert target.name == "贵州茅台"
    assert target.sector == "白酒"
    assert target.theme == "Consumer_Staples"
    assert target.ecosystem_role == "downstream_app"

from __future__ import annotations

from fastapi.testclient import TestClient

from sentinel.web.main import create_app
from sentinel.web.services.fundamental_advice_service import (
    FundamentalAdviceResult,
    FundamentalScoreProposal,
    TradingAgentsEvidence,
)


def test_fundamental_advice_route_renders_traceable_proposal(monkeypatch):
    result = FundamentalAdviceResult(
        symbol="600519",
        name="贵州茅台",
        market="A_SHARE",
        sector="白酒",
        provider="fake_tradingagents",
        ticker="600519.SS",
        status="completed",
        boundary="advisory_only",
        summary="多智能体建议复核品牌溢价。",
        evidence=[
            TradingAgentsEvidence(
                source="Fundamentals Analyst",
                title="品牌溢价",
                detail="高端白酒心智仍强。",
            )
        ],
        counter_evidence=[
            TradingAgentsEvidence(
                source="Bear Researcher",
                title="渠道库存",
                detail="批价走弱时需要下修。",
                polarity="counter",
            )
        ],
        proposals=[
            FundamentalScoreProposal(
                dimension="brand_premium",
                label="品牌溢价",
                config_file="moat_static_base.yaml",
                path="companies.600519.base_score.brand_premium.score",
                current_score=95.0,
                proposed_score=96.0,
                confidence=0.74,
                rationale="证据支持小幅上调，但仍需人工确认。",
            )
        ],
        raw_decision="raw",
    )

    class FakeService:
        def generate(self, **kwargs):
            return result

    monkeypatch.setattr(
        "sentinel.web.routers.research._get_fundamental_advice_service",
        lambda: FakeService(),
    )

    response = TestClient(create_app()).post(
        "/api/fundamental-advice",
        data={"symbol": "600519", "market": "A_SHARE"},
    )

    assert response.status_code == 200
    assert "TradingAgents 基本面建议" in response.text
    assert "品牌溢价" in response.text
    assert "companies.600519.base_score.brand_premium.score" in response.text
    assert "不自动写入配置" in response.text
    assert "支持证据" in response.text
    assert "反向证据" in response.text

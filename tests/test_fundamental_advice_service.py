from __future__ import annotations

import sys
from pathlib import Path

import yaml

from sentinel.web.services.fundamental_advice_service import (
    FundamentalAdviceService,
    TradingAgentsEvidence,
    TradingAgentsFundamentalReport,
    TradingAgentsRunner,
)


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


class _FakeTradingAgentsRunner:
    def run(self, *, symbol: str, name: str | None, market: str, sector: str | None):
        assert symbol == "600519"
        assert name == "贵州茅台"
        return TradingAgentsFundamentalReport(
            provider="fake_tradingagents",
            ticker="600519.SS",
            summary="多智能体一致认为品牌溢价仍强，但渠道库存需要反向复核。",
            dimension_scores={
                "brand_premium": 96,
                "franchise_barrier": 88,
            },
            confidence=0.74,
            evidence=[
                TradingAgentsEvidence(
                    source="Fundamentals Analyst",
                    title="品牌溢价",
                    detail="高端白酒价格带仍具备消费者心智和定价权。",
                )
            ],
            counter_evidence=[
                TradingAgentsEvidence(
                    source="Bear Researcher",
                    title="渠道库存",
                    detail="若批价持续走弱，品牌溢价需要下修。",
                    polarity="counter",
                )
            ],
            raw_decision="structured fake report",
        )


def test_fundamental_advice_builds_traceable_score_proposals_without_editing_yaml(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    moat_path = config_dir / "moat_static_base.yaml"
    original_moat = {
        "companies": {
            "600519": {
                "name": "贵州茅台",
                "sector": "白酒",
                "base_score": {
                    "brand_premium": {"score": 95, "note": "社交货币属性"},
                    "franchise_barrier": {"score": 90, "note": "产能壁垒"},
                },
            }
        }
    }
    _write_yaml(moat_path, original_moat)

    service = FundamentalAdviceService(
        config_dir=config_dir,
        runner=_FakeTradingAgentsRunner(),
    )
    result = service.generate(symbol="600519", market="A_SHARE")

    assert result.status == "completed"
    assert result.boundary == "advisory_only"
    assert result.provider == "fake_tradingagents"
    assert result.ticker == "600519.SS"
    assert result.evidence
    assert result.counter_evidence
    assert len(result.proposals) == 2
    first = result.proposals[0]
    assert first.config_file == "moat_static_base.yaml"
    assert first.path == "companies.600519.base_score.brand_premium.score"
    assert first.current_score == 95
    assert first.proposed_score == 96
    assert first.confidence == 0.74
    assert yaml.safe_load(moat_path.read_text(encoding="utf-8")) == original_moat


def test_fundamental_advice_reports_unavailable_when_tradingagents_is_not_ready(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {"companies": {"000001": {"name": "平安银行", "base_score": {}}}},
    )

    class BrokenRunner:
        def run(self, **kwargs):
            raise RuntimeError("TradingAgents 未安装或 API key 未配置")

    service = FundamentalAdviceService(config_dir=config_dir, runner=BrokenRunner())
    result = service.generate(symbol="000001", market="A_SHARE")

    assert result.status == "unavailable"
    assert result.proposals == []
    assert "TradingAgents 未安装" in result.summary
    assert result.counter_evidence


def test_fundamental_advice_sanitizes_provider_key_setup_examples(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(
        config_dir / "moat_static_base.yaml",
        {"companies": {"600519": {"name": "贵州茅台", "base_score": {}}}},
    )

    class MissingKeyRunner:
        def run(self, **kwargs):
            raise RuntimeError(
                "API key for provider 'openai' is not set. "
                "Please set the OPENAI_API_KEY environment variable "
                "(e.g. add OPENAI_API_KEY=your_key to your .env file)."
            )

    service = FundamentalAdviceService(config_dir=config_dir, runner=MissingKeyRunner())
    result = service.generate(symbol="600519", market="A_SHARE")

    assert result.status == "unavailable"
    assert "provider 'openai'" in result.summary
    assert "安全环境" in result.summary
    assert "OPENAI_API_KEY=your_key" not in result.summary
    assert ".env file" not in result.summary


def test_tradingagents_runner_uses_isolated_python_helper_when_configured(
    tmp_path, monkeypatch
):
    helper = tmp_path / "fake_tradingagents_helper.py"
    helper.write_text(
        """
from __future__ import annotations

import json
import sys

payload = {
    "provider": "TradingAgents isolated",
    "ticker": "600519.SS",
    "summary": "隔离环境已生成基本面建议",
    "dimension_scores": {"brand_premium": 91},
    "confidence": 0.68,
    "evidence": [
        {"source": "Fundamentals Analyst", "title": "品牌", "detail": "品牌力仍强"}
    ],
    "counter_evidence": [
        {"source": "Bear Researcher", "title": "库存", "detail": "渠道库存仍需复核"}
    ],
    "raw_decision": "args=" + repr(sys.argv[1:]),
}
print(json.dumps(payload, ensure_ascii=False))
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADINGAGENTS_PYTHON", sys.executable)
    monkeypatch.setenv("TRADINGAGENTS_HELPER_SCRIPT", str(helper))

    report = TradingAgentsRunner().run(
        symbol="600519",
        name="贵州茅台",
        market="A_SHARE",
        sector="白酒",
    )

    assert report.provider == "TradingAgents isolated"
    assert report.ticker == "600519.SS"
    assert report.dimension_scores == {"brand_premium": 91}
    assert report.confidence == 0.68
    assert report.evidence[0].source == "Fundamentals Analyst"
    assert report.counter_evidence[0].polarity == "counter"
    assert "--symbol" in report.raw_decision
    assert "600519" in report.raw_decision

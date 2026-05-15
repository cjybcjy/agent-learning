from __future__ import annotations

from datetime import datetime, timezone

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import AlertLevel, FactorScore, TargetInfo
from sentinel.mgfs.orchestrator import InvestmentDecision
from sentinel.publishers.mgfs_report import (
    MGFSReportPublisher,
    build_feishu_card,
    build_text_report,
)


def _make_decision(
    symbol: str = "600519",
    rating: str = "Avoid",
    alert_level: AlertLevel = AlertLevel.GREEN_PASS,
    circuit_breakers: list | None = None,
) -> InvestmentDecision:
    target = TargetInfo(symbol=symbol, market=Market.A_SHARE, asset_class="equity", sector="白酒")
    moat_score = FactorScore(factor_key="moat", factor_name="护城河深度", score=80.0)
    valuation_score = FactorScore(
        factor_key="valuation",
        factor_name="估值水位",
        score=45.0,
        details={"zone": "avoid", "primary_percentile": 85.0, "primary_metric": "PE_TTM"},
    )
    return InvestmentDecision(
        target=target,
        generated_at=datetime.now(tz=timezone.utc),
        factor_scores={"moat": moat_score, "valuation": valuation_score},
        raw_total=55.0,
        policy_multiplier=1.0,
        final_score=55.0,
        rating=rating,
        action="回避",
        circuit_breakers_triggered=circuit_breakers or [],
        alert_level=alert_level,
        report_sections={"overall_confidence": 0.8, "watermark": ""},
    )


class TestBuildFeishuCard:
    def test_card_has_header(self) -> None:
        decision = _make_decision()
        card = build_feishu_card(decision)
        assert "header" in card
        assert card["header"]["title"]["content"] == "🔴 600519 — Avoid"

    def test_hard_veto_has_red_header(self) -> None:
        decision = _make_decision(alert_level=AlertLevel.HARD_VETO)
        card = build_feishu_card(decision)
        assert card["header"]["template"] == "red"

    def test_strong_buy_has_green_header(self) -> None:
        decision = _make_decision(rating="Strong Buy", alert_level=AlertLevel.GREEN_PASS)
        card = build_feishu_card(decision)
        assert card["header"]["template"] == "green"
        assert "🟢" in card["header"]["title"]["content"]

    def test_circuit_breakers_in_card(self) -> None:
        cb = {"alert_level": "hard_veto", "message": "一票否决测试"}
        decision = _make_decision(alert_level=AlertLevel.HARD_VETO, circuit_breakers=[cb])
        card = build_feishu_card(decision)
        # Find the circuit breaker section
        elements = card["elements"]
        texts = [e["text"]["content"] for e in elements if e.get("tag") == "div"]
        assert any("一票否决测试" in t for t in texts)

    def test_watermark_in_card(self) -> None:
        decision = _make_decision()
        decision.report_sections["watermark"] = "[数据部分缺失]"
        card = build_feishu_card(decision)
        elements = card["elements"]
        texts = [e["text"]["content"] for e in elements if e.get("tag") == "div"]
        assert any("[数据部分缺失]" in t for t in texts)


class TestBuildTextReport:
    def test_text_contains_symbol(self) -> None:
        decision = _make_decision()
        text = build_text_report(decision)
        assert "600519" in text
        assert "护城河深度" in text
        assert "估值水位" in text

    def test_text_contains_circuit_breaker(self) -> None:
        cb = {"alert_level": "soft_veto", "message": "护城河评分过低"}
        decision = _make_decision(alert_level=AlertLevel.SOFT_VETO, circuit_breakers=[cb])
        text = build_text_report(decision)
        assert "护城河评分过低" in text


class TestMGFSReportPublisher:
    def test_publish_without_webhook_prints_to_console(self, capsys) -> None:
        publisher = MGFSReportPublisher(webhook_url=None)
        decision = _make_decision()
        publisher.publish(decision)
        captured = capsys.readouterr()
        assert "600519" in captured.out

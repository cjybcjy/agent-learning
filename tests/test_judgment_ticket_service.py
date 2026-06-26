from datetime import datetime

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import AlertLevel, FactorScore, TargetInfo
from sentinel.mgfs.orchestrator import InvestmentDecision


def _sample_decision() -> InvestmentDecision:
    return InvestmentDecision(
        target=TargetInfo(
            symbol="600519",
            market=Market.A_SHARE,
            asset_class="equity",
            name="贵州茅台",
            sector="白酒",
        ),
        generated_at=datetime.now(),
        factor_scores={
            "moat": FactorScore(
                factor_key="moat",
                factor_name="护城河",
                score=82.0,
                confidence=0.72,
                details={
                    "trend_score": 78.0,
                    "safety_score": 70.0,
                    "evidence_coverage": 0.65,
                },
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
                        "exit_label": "none",
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


def test_build_judgment_ticket_turns_factor_scores_into_research_dimensions():
    try:
        from sentinel.web.services.judgment_ticket_service import build_judgment_ticket
    except ImportError:
        pytest.fail("judgment ticket service is not implemented")

    ticket = build_judgment_ticket(_sample_decision())

    assert ticket.symbol == "600519"
    assert ticket.market == "A股"
    assert ticket.market_key == "A_SHARE"
    assert ticket.risk_gate.status == "warning"
    assert ticket.risk_gate.label == "风险闸门"
    assert [dimension.label for dimension in ticket.dimensions] == [
        "盈利能力",
        "增长",
        "财务安全",
        "估值",
        "政策传导",
        "技术趋势",
    ]
    assert 0 <= ticket.total_score <= 12
    assert ticket.conclusion in {
        "停止研究 / 数据或基本面不足",
        "继续观察 / 补证据",
        "进入重点研究池",
    }
    assert ticket.uncertainty


def test_build_judgment_ticket_generates_executable_data_tasks():
    try:
        from sentinel.web.services.judgment_ticket_service import build_judgment_ticket
    except ImportError:
        pytest.fail("judgment ticket service is not implemented")

    ticket = build_judgment_ticket(_sample_decision())
    task_keys = [task.task_key for task in ticket.next_tasks]

    assert task_keys[:2] == ["risk_announcements", "financial_metrics"]
    assert ticket.next_tasks[0].label == "巨潮风险公告核验"
    assert ticket.next_tasks[0].source == "cninfo"
    assert ticket.next_tasks[0].priority == "high"
    assert ticket.next_tasks[1].source == "akshare"
    assert "风险闸门" in ticket.next_tasks[0].reason


def test_build_judgment_ticket_keeps_risk_events_as_a_veto_gate():
    try:
        from sentinel.web.services.judgment_ticket_service import build_judgment_ticket
    except ImportError:
        pytest.fail("judgment ticket service is not implemented")

    decision = _sample_decision()
    decision.circuit_breakers_triggered.append(
        {
            "alert_level": "hard_veto",
            "message": "财务造假或退市风险触发硬性否决",
        }
    )
    decision.alert_level = AlertLevel.HARD_VETO

    ticket = build_judgment_ticket(decision)

    assert ticket.risk_gate.status == "veto"
    assert ticket.conclusion == "风险闸门未过，停止研究"
    assert "财务造假" in ticket.risk_gate.reason

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentinel.mgfs.factor_plugin import AlertLevel, FactorScore
from sentinel.mgfs.orchestrator import InvestmentDecision


@dataclass(frozen=True, slots=True)
class JudgmentDimension:
    key: str
    label: str
    needed_data: str
    rule: str
    score: int
    reason: str


@dataclass(frozen=True, slots=True)
class JudgmentRiskGate:
    status: str
    label: str
    needed_data: str
    rule: str
    reason: str


@dataclass(frozen=True, slots=True)
class JudgmentDataTask:
    task_key: str
    label: str
    source: str
    priority: str
    reason: str
    scope: str


@dataclass(frozen=True, slots=True)
class JudgmentTicket:
    symbol: str
    market: str
    market_key: str
    risk_gate: JudgmentRiskGate
    dimensions: list[JudgmentDimension]
    total_score: int
    conclusion: str
    uncertainty: str
    next_data: list[str]
    next_tasks: list[JudgmentDataTask]


def build_judgment_ticket(decision: InvestmentDecision) -> JudgmentTicket:
    dimensions = [
        _profitability_dimension(decision),
        _growth_dimension(decision),
        _financial_safety_dimension(decision),
        _valuation_dimension(decision),
        _policy_dimension(decision),
        _technical_trend_dimension(decision),
    ]
    risk_gate = _risk_gate(decision)
    total_score = sum(d.score for d in dimensions)
    return JudgmentTicket(
        symbol=decision.target.symbol,
        market=getattr(decision.target.market, "value", str(decision.target.market)),
        market_key=getattr(decision.target.market, "name", str(decision.target.market)),
        risk_gate=risk_gate,
        dimensions=dimensions,
        total_score=total_score,
        conclusion=_conclusion(total_score, risk_gate),
        uncertainty=_uncertainty(decision, dimensions, risk_gate),
        next_data=_next_data(dimensions, risk_gate),
        next_tasks=_next_tasks(dimensions, risk_gate),
    )


def _profitability_dimension(decision: InvestmentDecision) -> JudgmentDimension:
    moat = decision.factor_scores.get("moat")
    score = _factor_bucket(moat)
    if moat and (_has_missing_data_warning(moat) or moat.confidence < 0.75):
        score = min(score, 1)
    return JudgmentDimension(
        key="profitability",
        label="盈利能力",
        needed_data="ROE、毛利率、净利率、经营现金流、护城河证据",
        rule="持续盈利证据充足给 2，证据部分缺失给 1，证据不足或置信度低给 0",
        score=score,
        reason=_factor_reason(moat, "护城河/盈利质量证据不足", extra_detail="盈利质量与护城河证据"),
    )


def _growth_dimension(decision: InvestmentDecision) -> JudgmentDimension:
    moat = decision.factor_scores.get("moat")
    trend_score = _numeric_detail(moat, "trend_score")
    if trend_score is None:
        score = 1 if moat and moat.confidence >= 0.65 and moat.score >= 60 else 0
        reason = "未拿到独立增长指标，暂用护城河趋势与静态评分作弱证据"
    elif trend_score >= 80 and moat and moat.confidence >= 0.75:
        score = 2
        reason = f"趋势分 {trend_score:.1f}，增长证据较完整"
    elif trend_score >= 50 and moat and moat.confidence >= 0.5:
        score = 1
        reason = f"趋势分 {trend_score:.1f}，但仍需收入、利润和订单来源验证"
    else:
        score = 0
        reason = f"趋势分 {trend_score:.1f}，增长证据不足" if trend_score is not None else "增长证据不足"
    return JudgmentDimension(
        key="growth",
        label="增长",
        needed_data="收入增速、利润增速、订单/产能/份额变化、增长来源说明",
        rule="增长来源清晰且趋势分高给 2，只有部分趋势证据给 1，增长证据不足给 0",
        score=score,
        reason=reason,
    )


def _financial_safety_dimension(decision: InvestmentDecision) -> JudgmentDimension:
    moat = decision.factor_scores.get("moat")
    safety_score = _numeric_detail(moat, "safety_score")
    if _has_hard_risk(decision):
        score = 0
        reason = "风险事件已触发闸门，财务安全不得加分"
    elif safety_score is None:
        score = 1 if moat and moat.confidence >= 0.65 else 0
        reason = "未拿到独立财务安全指标，需补债务、现金流与治理数据"
    elif safety_score >= 75 and moat and moat.confidence >= 0.75:
        score = 2
        reason = f"安全分 {safety_score:.1f}，财务安全证据较完整"
    elif safety_score >= 50 and moat and moat.confidence >= 0.5:
        score = 1
        reason = f"安全分 {safety_score:.1f}，仍需补债务和现金流验证"
    else:
        score = 0
        reason = f"安全分 {safety_score:.1f}，财务安全证据不足" if safety_score is not None else "财务安全证据不足"
    return JudgmentDimension(
        key="financial_safety",
        label="财务安全",
        needed_data="资产负债率、短债现金比、经营现金流、商誉/应收、治理风险",
        rule="安全指标稳定给 2，部分数据可用给 1，债务/现金流/治理风险不清给 0",
        score=score,
        reason=reason,
    )


def _valuation_dimension(decision: InvestmentDecision) -> JudgmentDimension:
    valuation = decision.factor_scores.get("valuation")
    return JudgmentDimension(
        key="valuation",
        label="估值",
        needed_data="PE/PB/PS、历史分位、同行估值、增长匹配度、下跌空间",
        rule="相对历史和同行有安全边际给 2，估值中性给 1，明显偏贵或数据不足给 0",
        score=_factor_bucket(valuation),
        reason=_factor_reason(valuation, "估值数据不足", extra_detail="估值与安全边际"),
    )


def _policy_dimension(decision: InvestmentDecision) -> JudgmentDimension:
    policy = decision.factor_scores.get("policy")
    if policy:
        score = _factor_bucket(policy)
        policy_rating = policy.details.get("policy_rating") or decision.report_sections.get(
            "effective_policy_rating"
        )
        reason = (
            f"政策评级 {policy_rating or '未标注'}，"
            f"评分 {policy.score:.1f}，置信度 {policy.confidence:.0%}"
        )
    else:
        rating = str(decision.report_sections.get("effective_policy_rating", "neutral"))
        if rating in {"core_support", "favorable", "positive"}:
            score = 2
        elif rating in {"adverse", "negative", "restricted"}:
            score = 0
        else:
            score = 1
        reason = f"未启用政策因子，按当前政策口径 {rating} 作弱判断"
    return JudgmentDimension(
        key="policy_transmission",
        label="政策传导",
        needed_data="产业政策、监管口径、受益链条、公司可承接证据",
        rule="政策支持能传导到公司给 2，仅行业层面支持给 1，监管压制或传导不明给 0",
        score=score,
        reason=reason,
    )


def _technical_trend_dimension(decision: InvestmentDecision) -> JudgmentDimension:
    timing = decision.factor_scores.get("timing")
    technical_signal = _detail(timing, "technical_signal")
    exit_label = _nested_value(technical_signal, "exit_label")
    score = _factor_bucket(timing)
    if exit_label == "exit_risk" or _has_timing_risk_warning(timing):
        score = 0
    return JudgmentDimension(
        key="technical_trend",
        label="技术趋势",
        needed_data="MA60、RSI、量能、趋势斜率、观察区间、风险参考位",
        rule="趋势结构健康给 2，中性或仅观察给 1，破位/择时风险触发给 0",
        score=score,
        reason=_factor_reason(timing, "技术趋势数据不足", extra_detail="Freqtrade-style 技术信号"),
    )


def _risk_gate(decision: InvestmentDecision) -> JudgmentRiskGate:
    hard_reason = _hard_risk_reason(decision)
    if hard_reason:
        status = "veto"
        reason = hard_reason
    else:
        warning_reason = _warning_risk_reason(decision)
        status = "warning" if warning_reason else "pass"
        reason = warning_reason or "未检测到硬性风险事件"
    return JudgmentRiskGate(
        status=status,
        label="风险闸门",
        needed_data="退市/监管处罚/财务造假/债务爆雷/治理混乱/重大诉讼公告",
        rule="硬风险一票否决；数据缺失、低置信度或软风险进入警示，不参与总分加分",
        reason=reason,
    )


def _conclusion(total_score: int, risk_gate: JudgmentRiskGate) -> str:
    if risk_gate.status == "veto":
        return "风险闸门未过，停止研究"
    if total_score <= 4:
        return "停止研究 / 数据或基本面不足"
    if total_score <= 8:
        return "继续观察 / 补证据"
    return "进入重点研究池"


def _uncertainty(
    decision: InvestmentDecision,
    dimensions: list[JudgmentDimension],
    risk_gate: JudgmentRiskGate,
) -> str:
    if risk_gate.status in {"veto", "warning"}:
        return risk_gate.reason
    watermark = str(decision.report_sections.get("watermark", "")).strip()
    if watermark:
        return watermark
    weakest = min(dimensions, key=lambda d: d.score)
    return f"最不放心的是{weakest.label}: {weakest.reason}"


def _next_data(
    dimensions: list[JudgmentDimension], risk_gate: JudgmentRiskGate
) -> list[str]:
    if risk_gate.status != "pass":
        return [risk_gate.needed_data]
    weak_dimensions = [d for d in dimensions if d.score < 2]
    return [d.needed_data for d in weak_dimensions[:3]]


def _next_tasks(
    dimensions: list[JudgmentDimension], risk_gate: JudgmentRiskGate
) -> list[JudgmentDataTask]:
    tasks: list[JudgmentDataTask] = []

    def add(task: JudgmentDataTask) -> None:
        if task.task_key not in {existing.task_key for existing in tasks}:
            tasks.append(task)

    if risk_gate.status != "pass":
        add(
            JudgmentDataTask(
                task_key="risk_announcements",
                label="巨潮风险公告核验",
                source="cninfo",
                priority="high",
                reason=f"{risk_gate.label}: {risk_gate.reason}",
                scope="监管处罚、问询函、诉讼仲裁、质押、担保、减持",
            )
        )

    weak_keys = {dimension.key for dimension in dimensions if dimension.score < 2}
    if weak_keys & {"profitability", "growth", "financial_safety"}:
        add(
            JudgmentDataTask(
                task_key="financial_metrics",
                label="AkShare 财务指标补齐",
                source="akshare",
                priority="high" if "financial_safety" in weak_keys else "medium",
                reason="盈利、增长或财务安全维度证据不足",
                scope="ROE、毛利率、资产负债率、现金流/净利润、商誉占比",
            )
        )
    if weak_keys & {"profitability", "growth"}:
        add(
            JudgmentDataTask(
                task_key="periodic_reports",
                label="巨潮定期报告证据",
                source="cninfo",
                priority="medium",
                reason="盈利和增长需要回到年报、半年报、季报验证",
                scope="年报、半年报、季报及经营数据说明",
            )
        )
    if not tasks:
        add(
            JudgmentDataTask(
                task_key="periodic_reports",
                label="巨潮定期报告证据",
                source="cninfo",
                priority="low",
                reason="补充最新公告证据以提高结论可追溯性",
                scope="年报、半年报、季报",
            )
        )
    return tasks[:3]


def _factor_bucket(score: FactorScore | None) -> int:
    if score is None:
        return 0
    if score.confidence < 0.5 or score.score < 50:
        return 0
    if score.score >= 75 and score.confidence >= 0.75:
        return 2
    return 1


def _factor_reason(
    score: FactorScore | None, missing_reason: str, *, extra_detail: str
) -> str:
    if score is None:
        return missing_reason
    parts = [
        f"{extra_detail}评分 {score.score:.1f}",
        f"置信度 {score.confidence:.0%}",
    ]
    if score.warnings:
        parts.append(f"提示: {score.warnings[0]}")
    return "，".join(parts)


def _has_hard_risk(decision: InvestmentDecision) -> bool:
    return bool(_hard_risk_reason(decision))


def _hard_risk_reason(decision: InvestmentDecision) -> str:
    alert_value = _alert_value(decision.alert_level)
    if alert_value == AlertLevel.HARD_VETO.value:
        return _first_circuit_breaker_message(decision) or "硬性风险闸门触发"
    for score in decision.factor_scores.values():
        if score.is_veto:
            return score.veto_reason or f"{score.factor_name}触发否决"
    for breaker in decision.circuit_breakers_triggered:
        breaker_level = str(breaker.get("alert_level", "")).lower()
        if "hard" in breaker_level or "veto" in breaker_level:
            return str(breaker.get("message") or "风险熔断触发")
    return ""


def _warning_risk_reason(decision: InvestmentDecision) -> str:
    watermark = str(decision.report_sections.get("watermark", "")).strip()
    if watermark:
        return watermark
    gate_failures = decision.report_sections.get("rating_gate_failures") or []
    if gate_failures:
        return "评级证据不足，需补关键因子"
    confidence = decision.report_sections.get("overall_confidence")
    if isinstance(confidence, (int, float)) and confidence < 0.8:
        return f"总体置信度 {confidence:.0%}，数据仍需补齐"
    alert_value = _alert_value(decision.alert_level)
    if alert_value in {AlertLevel.SOFT_VETO.value, AlertLevel.YELLOW_WARNING.value}:
        return "存在软性风险或黄色预警，需人工复核"
    for score in decision.factor_scores.values():
        for warning in score.warnings:
            if _warning_mentions_risk(warning):
                return warning
    return ""


def _first_circuit_breaker_message(decision: InvestmentDecision) -> str:
    for breaker in decision.circuit_breakers_triggered:
        message = breaker.get("message")
        if message:
            return str(message)
    return ""


def _alert_value(alert_level: AlertLevel | str) -> str:
    return getattr(alert_level, "value", str(alert_level))


def _numeric_detail(score: FactorScore | None, key: str) -> float | None:
    value = _detail(score, key)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _detail(score: FactorScore | None, key: str) -> Any:
    if score is None:
        return None
    return score.details.get(key)


def _nested_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _has_missing_data_warning(score: FactorScore) -> bool:
    return any("缺失" in warning or "数据" in warning for warning in score.warnings)


def _has_timing_risk_warning(score: FactorScore | None) -> bool:
    if score is None:
        return False
    return any("择时" in warning and "风险" in warning for warning in score.warnings)


def _warning_mentions_risk(warning: str) -> bool:
    risk_keywords = ("退市", "造假", "债务", "治理", "监管", "诉讼", "爆雷", "系统故障")
    return any(keyword in warning for keyword in risk_keywords)

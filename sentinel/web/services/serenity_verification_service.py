from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sentinel.config import AppSettings
from sentinel.mgfs.moat_evidence import MoatEvidenceAuditor


DIMENSION_LABELS = {
    "brand_premium": "品牌溢价",
    "franchise_barrier": "壁垒/牌照",
    "switching_cost": "切换成本",
    "network_effect": "网络效应",
    "cost_advantage": "成本优势",
}


@dataclass(frozen=True, slots=True)
class SerenityEvidenceGap:
    dimension: str
    label: str
    missing_fields: list[str]
    source_paths: list[str]
    verification_items: list[str]
    config_patch_hint: str


@dataclass(frozen=True, slots=True)
class SerenityMetricTarget:
    metric_name: str
    target_table: str
    source_paths: list[str]
    financial_items: list[str]
    calculation_hint: str
    reason: str


@dataclass(frozen=True, slots=True)
class SerenityVerificationPlan:
    symbol: str
    market: str
    company_name: str | None
    sector: str | None
    boundary: str
    summary: str
    evidence_gaps: list[SerenityEvidenceGap] = field(default_factory=list)
    metric_targets: list[SerenityMetricTarget] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


class SerenityVerificationService:
    """Translate Serenity research method into a read-only source checklist."""

    def __init__(self, config_dir: Path | str | None = None) -> None:
        settings = AppSettings()
        self.config_dir = (
            Path(config_dir) if config_dir is not None else settings.resolved_config_dir
        )
        self._auditor = MoatEvidenceAuditor()

    def build_plan(self, *, symbol: str, market: str) -> SerenityVerificationPlan:
        moat_data = self._load_moat_data()
        company = self._company_config(moat_data, symbol)
        base_score = company.get("base_score", {})
        if not isinstance(base_score, dict):
            base_score = {}

        evidence_gaps = self._build_evidence_gaps(symbol, base_score)
        metric_targets = _default_metric_targets()
        company_name = _optional_str(company.get("name"))
        sector = _optional_str(company.get("sector"))
        summary = (
            "先用 Serenity 方法把护城河判断拆成可验证来源，再把财报项映射到 "
            "trend_metrics / safety_metrics；当前只生成路线图，不自动写入配置或数据库。"
        )
        return SerenityVerificationPlan(
            symbol=symbol,
            market=market,
            company_name=company_name,
            sector=sector,
            boundary="read_only_verification_plan",
            summary=summary,
            evidence_gaps=evidence_gaps,
            metric_targets=metric_targets,
            next_actions=[
                "先补 source/as_of/confidence/bear_case，降低护城河主观性。",
                "再按 metric_targets 抓取年报、季报和现金流量表，写入 DuckDB 指标表。",
                "抓取后重新运行 MGFS 评估，观察 evidence_coverage 和 overall_confidence 是否提升。",
            ],
            limitations=[
                "路线图不是交易指令，也不会自动修改 moat_static_base.yaml。",
                "动态指标需要真实财报数据源落库后才会解除“仅使用静态评分”的 warning。",
            ],
        )

    def _build_evidence_gaps(
        self,
        symbol: str,
        base_score: dict[str, Any],
    ) -> list[SerenityEvidenceGap]:
        report = self._auditor.audit_base_scores(symbol, base_score)
        by_dimension: dict[str, list[str]] = {}
        for issue in report.issues:
            by_dimension.setdefault(issue.dimension, []).append(issue.field)

        gaps: list[SerenityEvidenceGap] = []
        for dimension, fields in by_dimension.items():
            missing_fields = sorted(set(fields), key=_evidence_field_order)
            gaps.append(
                SerenityEvidenceGap(
                    dimension=dimension,
                    label=DIMENSION_LABELS.get(dimension, dimension),
                    missing_fields=missing_fields,
                    source_paths=_source_paths_for_dimension(dimension),
                    verification_items=_verification_items_for_dimension(dimension),
                    config_patch_hint=(
                        f"companies.{symbol}.base_score.{dimension} "
                        "补 source/as_of/confidence/bear_case"
                    ),
                )
            )
        gaps.sort(key=lambda item: item.dimension)
        return gaps

    def _load_moat_data(self) -> dict[str, Any]:
        path = self.config_dir / "moat_static_base.yaml"
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _company_config(moat_data: dict[str, Any], symbol: str) -> dict[str, Any]:
        companies = moat_data.get("companies", {})
        if not isinstance(companies, dict):
            return {}
        company = companies.get(symbol, {})
        return company if isinstance(company, dict) else {}


def _source_paths_for_dimension(dimension: str) -> list[str]:
    common = ["年报/半年报/季报", "临时公告", "交易所问询函/监管函"]
    mapping = {
        "brand_premium": [
            "年报：品牌、渠道、产品价格带、分产品收入与毛利率",
            "投资者关系活动记录/业绩说明会：价格体系、渠道库存、批价",
            "行业协会/可信媒体：市场份额、价格带变化",
        ],
        "franchise_barrier": [
            "年报：核心资产、产能、资质、专利、关键工艺",
            "环评/能评/地方项目备案：产线扩张和审批约束",
            "专利/标准/认证记录：技术或资质壁垒",
        ],
        "switching_cost": [
            "年报：客户结构、合同期限、服务网络、存量客户续约",
            "招投标/中标公告：客户认证和替换周期",
            "上下游上市公司公告：供应链绑定关系",
        ],
        "network_effect": [
            "年报：用户数、连接设备、生态伙伴、平台交易规模",
            "产品/平台公告：互联互通、开发者或渠道生态",
            "行业数据：网络规模是否带来边际价值提升",
        ],
        "cost_advantage": [
            "年报/季报：毛利率、费用率、单位成本、产能利用率",
            "在建工程/固定资产：扩产和折旧压力",
            "现金流量表：经营现金流与利润匹配度",
        ],
    }
    return mapping.get(dimension, common)


def _verification_items_for_dimension(dimension: str) -> list[str]:
    mapping = {
        "brand_premium": ["高端价格带占比", "毛利率相对同行", "渠道库存与批价反向验证"],
        "franchise_barrier": ["资质/专利/核心资产是否稀缺", "扩产审批周期", "替代供应商数量"],
        "switching_cost": ["客户认证周期", "存量客户续约或复购", "替换成本是否影响停线/调参/合规"],
        "network_effect": ["用户或设备规模", "生态伙伴数量", "规模扩大是否改善单位经济"],
        "cost_advantage": ["毛利率稳定性", "费用率趋势", "产能利用率与经营现金流"],
    }
    return mapping.get(dimension, ["补充强证据来源", "补充反方验证"])


def _default_metric_targets() -> list[SerenityMetricTarget]:
    return [
        SerenityMetricTarget(
            metric_name="roic_sustainability",
            target_table="trend_metrics",
            source_paths=["年报/季报：利润表、资产负债表、财务附注"],
            financial_items=["净利润", "所得税费用", "有息负债", "所有者权益", "货币资金"],
            calculation_hint="用近 3-5 期 ROIC 稳定性映射为 0-100 分。",
            reason="验证护城河是否真的转化为持续资本回报。",
        ),
        SerenityMetricTarget(
            metric_name="gmoat_stability",
            target_table="trend_metrics",
            source_paths=["年报/季报：主营业务分产品收入、毛利率"],
            financial_items=["营业收入", "营业成本", "分产品毛利率"],
            calculation_hint="毛利率水平、波动和相对同行优势映射为 0-100 分。",
            reason="验证品牌/壁垒/成本优势是否体现在利润质量上。",
        ),
        SerenityMetricTarget(
            metric_name="rd_efficiency",
            target_table="trend_metrics",
            source_paths=["年报：研发费用、研发人员、专利与新品进展"],
            financial_items=["研发费用", "营业收入", "专利数量", "新产品收入"],
            calculation_hint="研发费用率与收入/毛利改善、专利产出做交叉验证。",
            reason="验证技术型护城河是否有投入产出效率。",
        ),
        SerenityMetricTarget(
            metric_name="debt_ratio_deterioration",
            target_table="safety_metrics",
            source_paths=["资产负债表：负债、资产、短债、长期借款"],
            financial_items=["资产总计", "负债合计", "短期借款", "长期借款"],
            calculation_hint="负债率恶化越明显，安全分越低。",
            reason="识别护城河被杠杆或扩产压力侵蚀的风险。",
        ),
        SerenityMetricTarget(
            metric_name="goodwill_ratio",
            target_table="safety_metrics",
            source_paths=["资产负债表/附注：商誉、无形资产、减值测试"],
            financial_items=["商誉", "资产总计", "商誉减值准备"],
            calculation_hint="商誉占比和减值迹象映射为安全分。",
            reason="避免把并购形成的表观规模误判为真实壁垒。",
        ),
        SerenityMetricTarget(
            metric_name="operating_cashflow_ratio",
            target_table="safety_metrics",
            source_paths=["现金流量表：经营活动现金流量净额"],
            financial_items=["经营活动现金流量净额", "净利润", "营业收入"],
            calculation_hint="经营现金流/净利润或经营现金流/收入越稳，安全分越高。",
            reason="验证利润是否能转成现金，排除应收和库存堆高。",
        ),
    ]


def _evidence_field_order(field: str) -> int:
    order = {"source": 0, "as_of": 1, "confidence": 2, "bear_case": 3}
    return order.get(field, 99)


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None

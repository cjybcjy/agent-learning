from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from sentinel.config import AppSettings
from sentinel.mgfs.evolution.research_artifacts import file_content_hash, stable_json_hash
from sentinel.mgfs.evolution.research_signal import MGFSAgentSignal, merge_mgfs_agent_signals
from sentinel.mgfs.moat_evidence import MoatEvidenceAuditor


@dataclass
class EvidenceItem:
    source: str
    title: str
    detail: str
    polarity: str = "supporting"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceItem":
        return cls(
            source=str(payload.get("source", "")),
            title=str(payload.get("title", "")),
            detail=str(payload.get("detail", "")),
            polarity=str(payload.get("polarity", "supporting")),
        )


@dataclass
class ResearchSuggestion:
    id: str
    category: str
    title: str
    target: str
    config_file: str
    rationale: str
    proposed_change: str
    confidence: float
    impact: str
    evidence: list[EvidenceItem]
    counter_evidence: list[EvidenceItem]
    status: str = "pending"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchSuggestion":
        return cls(
            id=str(payload.get("id", "")),
            category=str(payload.get("category", "")),
            title=str(payload.get("title", "")),
            target=str(payload.get("target", "")),
            config_file=str(payload.get("config_file", "")),
            rationale=str(payload.get("rationale", "")),
            proposed_change=str(payload.get("proposed_change", "")),
            confidence=float(payload.get("confidence", 0.0)),
            impact=str(payload.get("impact", "中")),
            evidence=[
                EvidenceItem.from_dict(item)
                for item in payload.get("evidence", [])
                if isinstance(item, dict)
            ],
            counter_evidence=[
                EvidenceItem.from_dict(item)
                for item in payload.get("counter_evidence", [])
                if isinstance(item, dict)
            ],
            status=str(payload.get("status", "pending")),
        )


@dataclass
class ResearchAgentRun:
    run_id: str
    generated_at: str
    mode: str
    status: str
    summary: str
    source_mix: dict[str, int]
    suggestions: list[ResearchSuggestion]
    artifact_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchAgentRun":
        return cls(
            run_id=str(payload.get("run_id", "")),
            generated_at=str(payload.get("generated_at", "")),
            mode=str(payload.get("mode", "read_only_advisory")),
            status=str(payload.get("status", "completed")),
            summary=str(payload.get("summary", "")),
            source_mix={
                str(key): int(value)
                for key, value in payload.get("source_mix", {}).items()
            },
            suggestions=[
                ResearchSuggestion.from_dict(item)
                for item in payload.get("suggestions", [])
                if isinstance(item, dict)
            ],
            artifact_dir=payload.get("artifact_dir"),
        )


class ResearchAgentService:
    """Read-only daily config review for the Ops workspace."""

    STALE_AFTER_DAYS = 21
    ALLOWED_STATUSES = {"pending", "queued", "watching", "rejected"}

    def __init__(
        self,
        config_dir: Path | str | None = None,
        store_path: Path | str | None = None,
        external_signal_path: Path | str | None = None,
        artifact_root: Path | str | None = None,
        today: date | str | None = None,
    ) -> None:
        settings = AppSettings()
        self.config_dir = Path(config_dir) if config_dir is not None else settings.resolved_config_dir
        self.store_path = (
            Path(store_path)
            if store_path is not None
            else settings.database_path.parent / "research_agent_runs.json"
        )
        self.external_signal_path = (
            Path(external_signal_path)
            if external_signal_path is not None
            else settings.database_path.parent / "research_external_signals.json"
        )
        self.artifact_root = (
            Path(artifact_root)
            if artifact_root is not None
            else settings.database_path.parent / "mgfs_research_runs"
        )
        self.today = self._coerce_date(today)
        self._moat_evidence_auditor = MoatEvidenceAuditor()

    def ensure_daily_review(self) -> ResearchAgentRun:
        latest = self.load_latest_run()
        if latest is not None:
            generated_date = _parse_date(latest.generated_at[:10])
            if generated_date == self.today:
                return latest
        return self.run_daily_review()

    def run_daily_review(self) -> ResearchAgentRun:
        loaded_configs = {
            "policy_whitelist.yaml": self._load_yaml_file("policy_whitelist.yaml"),
            "ecosystem_themes.yaml": self._load_yaml_file("ecosystem_themes.yaml"),
            "moat_static_base.yaml": self._load_yaml_file("moat_static_base.yaml"),
        }
        external_signals = self._load_external_signals()
        suggestions: list[ResearchSuggestion] = []

        for filename, data in loaded_configs.items():
            freshness = self._freshness_suggestion(filename, data)
            if freshness is not None:
                suggestions.append(freshness)

        moat_data = loaded_configs["moat_static_base.yaml"]
        theme_concentration = self._theme_concentration_suggestion(moat_data)
        if theme_concentration is not None:
            suggestions.append(theme_concentration)
        moat_evidence = self._moat_evidence_suggestion(moat_data)
        if moat_evidence is not None:
            suggestions.append(moat_evidence)

        ecosystem_data = loaded_configs["ecosystem_themes.yaml"]
        counter_bias = self._ecosystem_counter_bias_suggestion(ecosystem_data)
        if counter_bias is not None:
            suggestions.append(counter_bias)

        suggestions.extend(
            self._external_policy_suggestions(
                external_signals,
                loaded_configs["policy_whitelist.yaml"],
            )
        )
        suggestions.extend(
            self._external_moat_suggestions(
                external_signals,
                loaded_configs["moat_static_base.yaml"],
            )
        )

        now = datetime.now()
        run = ResearchAgentRun(
            run_id=f"RA_{self.today.strftime('%Y%m%d')}_{now.strftime('%H%M%S')}",
            generated_at=datetime.combine(self.today, now.time()).isoformat(timespec="seconds"),
            mode="read_only_advisory",
            status="completed",
            summary=self._build_summary(suggestions),
            source_mix={
                "internal_config": sum(1 for data in loaded_configs.values() if data),
                "contrarian_checks": sum(1 for item in suggestions if item.counter_evidence),
                "external_news": len(external_signals),
            },
            suggestions=suggestions,
        )
        run.artifact_dir = str(self._write_daily_artifacts(run))
        self._persist_run(run)
        return run

    def load_latest_run(self) -> ResearchAgentRun | None:
        payload = self._read_payload()
        latest = payload.get("latest_run")
        if not isinstance(latest, dict):
            return None
        return ResearchAgentRun.from_dict(latest)

    def update_suggestion_status(
        self,
        suggestion_id: str,
        status: str,
    ) -> ResearchSuggestion:
        if status not in self.ALLOWED_STATUSES:
            raise ValueError(f"不支持的建议状态: {status}")

        run = self.load_latest_run()
        if run is None:
            raise ValueError("还没有可更新的 Agent 运行记录")

        for suggestion in run.suggestions:
            if suggestion.id == suggestion_id:
                suggestion.status = status
                self._persist_run(run)
                return suggestion
        raise ValueError(f"未找到建议: {suggestion_id}")

    def _load_yaml_file(self, filename: str) -> dict[str, Any]:
        path = self.config_dir / filename
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def _load_external_signals(self) -> list[dict[str, Any]]:
        if not self.external_signal_path.exists():
            return []
        try:
            payload = json.loads(self.external_signal_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = payload.get("items", [])
        else:
            return []
        return [item for item in items if isinstance(item, dict)]

    def _external_policy_suggestions(
        self,
        signals: list[dict[str, Any]],
        policy_data: dict[str, Any],
    ) -> list[ResearchSuggestion]:
        updated_at = _parse_date(policy_data.get("last_updated")) or date.min
        suggestions: list[ResearchSuggestion] = []
        for signal in signals:
            if signal.get("category") != "policy":
                continue
            published_at = _parse_date(signal.get("published_at"))
            if published_at is not None and published_at <= updated_at:
                continue
            target = _signal_target(signal, "sectors") or _signal_target(signal, "themes") or "政策信号"
            suggestions.append(
                ResearchSuggestion(
                    id=_stable_id(
                        "external_policy",
                        str(signal.get("published_at", "")),
                        str(signal.get("title", "")),
                        target,
                    ),
                    category="外部信号",
                    title="政策白名单有新外部信号待复核",
                    target=target,
                    config_file="policy_whitelist.yaml",
                    rationale=(
                        f"发现晚于政策白名单更新时间的外部政策信号："
                        f"{signal.get('title', '')}。"
                    ),
                    proposed_change=(
                        "核验原文与反向政策后，再决定是否调整 sector multiplier、policy_rating 或 note。"
                    ),
                    confidence=0.72,
                    impact=str(signal.get("impact") or "中"),
                    evidence=[_evidence_from_signal(signal)],
                    counter_evidence=[
                        EvidenceItem(
                            source="反向证据",
                            title="外部信号不等于配置结论",
                            detail="需要确认政策对象、执行力度、产业链受益位置和市场是否已充分定价。",
                            polarity="counter",
                        )
                    ],
                )
            )
        return suggestions

    def _external_moat_suggestions(
        self,
        signals: list[dict[str, Any]],
        moat_data: dict[str, Any],
    ) -> list[ResearchSuggestion]:
        companies = moat_data.get("companies", {})
        if not isinstance(companies, dict):
            return []
        suggestions: list[ResearchSuggestion] = []
        for signal in signals:
            if signal.get("category") != "moat":
                continue
            symbols = signal.get("symbols", [])
            if not isinstance(symbols, list):
                continue
            for symbol in symbols:
                cfg = companies.get(str(symbol))
                if not isinstance(cfg, dict):
                    continue
                name = str(cfg.get("name") or symbol)
                evidence = _evidence_from_signal(signal)
                counter_evidence = [
                    evidence
                    if signal.get("polarity") == "counter"
                    else EvidenceItem(
                        source="反向证据",
                        title="单条信号不能改写护城河",
                        detail="需要用财报、订单、竞争格局和价格能力交叉验证后再调整基础评分。",
                        polarity="counter",
                    )
                ]
                suggestions.append(
                    ResearchSuggestion(
                        id=_stable_id(
                            "external_moat",
                            str(symbol),
                            str(signal.get("published_at", "")),
                            str(signal.get("title", "")),
                        ),
                        category="外部信号",
                        title="护城河外部信号待复核",
                        target=f"{name}({symbol})",
                        config_file="moat_static_base.yaml",
                        rationale=(
                            f"{name} 出现需要复核护城河假设的外部信号："
                            f"{signal.get('title', '')}。"
                        ),
                        proposed_change=(
                            "补充 source/as_of/confidence/bear_case；如被多源证实，再调整对应 base_score 维度。"
                        ),
                        confidence=0.70,
                        impact=str(signal.get("impact") or "中"),
                        evidence=[
                            EvidenceItem(
                                source="本地配置",
                                title="当前护城河假设",
                                detail=f"{name} 已在 moat_static_base.yaml 中维护静态评分。",
                            )
                        ],
                        counter_evidence=counter_evidence,
                    )
                )
        return suggestions

    def _freshness_suggestion(
        self,
        filename: str,
        data: dict[str, Any],
    ) -> ResearchSuggestion | None:
        display_name = _display_name(filename)
        updated_at = _parse_date(data.get("last_updated"))

        if updated_at is None:
            if filename == "ecosystem_themes.yaml":
                title = "生态主题需要补充更新时间"
            else:
                title = f"{display_name}需要复核"
            rationale = f"{display_name}没有 last_updated，无法判断规则是否仍匹配当前市场。"
            evidence_detail = f"{filename} 未提供 last_updated 字段"
        else:
            age_days = (self.today - updated_at).days
            if age_days <= self.STALE_AFTER_DAYS:
                return None
            title = f"{display_name}需要复核"
            rationale = (
                f"{display_name}距离上次更新已有 {age_days} 天，超过 "
                f"{self.STALE_AFTER_DAYS} 天复核窗口。"
            )
            evidence_detail = (
                f"{filename} last_updated={updated_at.isoformat()}，"
                f"距今天 {age_days} 天"
            )

        return ResearchSuggestion(
            id=_stable_id("freshness", filename, display_name, title),
            category="配置新鲜度",
            title=title,
            target=display_name,
            config_file=filename,
            rationale=rationale,
            proposed_change=(
                "先查看近期政策、财报和产业链变化，再决定是否在配置控制台调整对应规则。"
            ),
            confidence=0.86,
            impact="中",
            evidence=[
                EvidenceItem(
                    source="本地配置",
                    title="更新时间检查",
                    detail=evidence_detail,
                )
            ],
            counter_evidence=[
                EvidenceItem(
                    source="反向证据",
                    title="陈旧不等于失效",
                    detail="配置时间较旧只说明需要复核，不能单独证明原假设已经错误。",
                    polarity="counter",
                )
            ],
        )

    def _theme_concentration_suggestion(
        self,
        moat_data: dict[str, Any],
    ) -> ResearchSuggestion | None:
        companies = moat_data.get("companies", {})
        if not isinstance(companies, dict) or len(companies) < 3:
            return None

        themes = [
            str(cfg.get("theme") or "未分类")
            for cfg in companies.values()
            if isinstance(cfg, dict)
        ]
        if not themes:
            return None

        counts = Counter(themes)
        top_theme, top_count = counts.most_common(1)[0]
        share = top_count / len(themes)
        if share < 0.40:
            return None

        return ResearchSuggestion(
            id=_stable_id("concentration", "moat_static_base.yaml", top_theme, "主题覆盖过于集中"),
            category="覆盖偏差",
            title="主题覆盖过于集中",
            target=top_theme,
            config_file="moat_static_base.yaml",
            rationale=(
                f"{top_theme} 覆盖 {top_count}/{len(themes)} 个标的，"
                f"占比 {share:.0%}，可能放大单一叙事。"
            ),
            proposed_change=(
                "增加同产业链的反方样本、替代赛道或周期弱相关标的，再决定是否调整基础评分。"
            ),
            confidence=0.78,
            impact="高",
            evidence=[
                EvidenceItem(
                    source="本地配置",
                    title="主题分布",
                    detail=f"{top_theme}: {top_count}/{len(themes)}，占比 {share:.0%}",
                )
            ],
            counter_evidence=[
                EvidenceItem(
                    source="反向证据",
                    title="集中也可能来自真实主线",
                    detail="如果该主题正处于确定性扩张期，集中覆盖不必机械摊薄，但需要额外验证风险。",
                    polarity="counter",
                )
            ],
        )

    def _ecosystem_counter_bias_suggestion(
        self,
        ecosystem_data: dict[str, Any],
    ) -> ResearchSuggestion | None:
        contrarian_keys = {
            "negative_watchlist",
            "contrarian_watchlist",
            "cooling_signals",
            "risk_themes",
            "bear_cases",
        }
        if any(key in ecosystem_data for key in contrarian_keys):
            return None

        hot_themes = ecosystem_data.get("hot_themes", [])
        hot_theme_count = len(hot_themes) if isinstance(hot_themes, list) else 0
        return ResearchSuggestion(
            id=_stable_id(
                "contrarian",
                "ecosystem_themes.yaml",
                "negative_watchlist",
                "生态主题缺少反向观察池",
            ),
            category="反方校验",
            title="生态主题缺少反向观察池",
            target="negative_watchlist",
            config_file="ecosystem_themes.yaml",
            rationale=(
                "当前生态主题配置只表达正向热主题，没有显式记录降温信号、反方样本或淘汰条件。"
            ),
            proposed_change=(
                "在生态主题配置中增加 negative_watchlist 或 cooling_signals，用来记录主题降温和证伪线索。"
            ),
            confidence=0.82,
            impact="高",
            evidence=[
                EvidenceItem(
                    source="本地配置",
                    title="正向主题数量",
                    detail=f"hot_themes 当前记录 {hot_theme_count} 个主题，未发现反向观察字段",
                )
            ],
            counter_evidence=[
                EvidenceItem(
                    source="反向证据",
                    title="字段缺失不代表没有人工复核",
                    detail="用户可能已经在外部笔记中维护反方观点；Agent 这里只能证明系统内缺少结构化入口。",
                    polarity="counter",
                )
            ],
        )

    def _moat_evidence_suggestion(
        self,
        moat_data: dict[str, Any],
    ) -> ResearchSuggestion | None:
        report = self._moat_evidence_auditor.audit_config(moat_data)
        if report.total_items == 0 or report.coverage >= 1.0:
            return None

        return ResearchSuggestion(
            id=_stable_id(
                "moat_evidence",
                "moat_static_base.yaml",
                "base_score",
                "护城河评分缺少证据字段",
            ),
            category="证据覆盖",
            title="护城河评分缺少证据字段",
            target="base_score",
            config_file="moat_static_base.yaml",
            rationale=(
                f"护城河静态评分证据字段覆盖率 {report.coverage:.0%}，"
                f"缺失 {report.missing_count} 项，无效 {report.invalid_count} 项。"
            ),
            proposed_change=(
                "为高影响 base_score 维度补充 source/as_of/confidence/bear_case，"
                "再决定是否调整分数。"
            ),
            confidence=0.88,
            impact="高" if report.coverage < 0.60 else "中",
            evidence=[
                EvidenceItem(
                    source="本地配置",
                    title="护城河证据字段覆盖",
                    detail=(
                        f"base_score 条目 {report.total_items} 个，"
                        f"必填证据字段 {report.required_fields} 项，"
                        f"覆盖率 {report.coverage:.0%}"
                    ),
                )
            ],
            counter_evidence=[
                EvidenceItem(
                    source="反向证据",
                    title="旧评分可作为初始假设",
                    detail="缺少结构化证据不代表评分一定错误，但不应把它当作高置信度结论。",
                    polarity="counter",
                )
            ],
        )

    def _build_summary(self, suggestions: list[ResearchSuggestion]) -> str:
        if not suggestions:
            return "今日未发现需要立即处理的配置偏差，建议保持观察。"
        high_impact = sum(1 for item in suggestions if item.impact == "高")
        return (
            f"今日生成 {len(suggestions)} 条只读建议，其中 {high_impact} 条高影响；"
            "建议先看证据和反向证据，再进入 YAML 编辑。"
        )

    def _persist_run(self, run: ResearchAgentRun) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._read_payload()
        runs = payload.get("runs", [])
        if not isinstance(runs, list):
            runs = []
        runs = [run.to_dict()] + runs[:19]
        self.store_path.write_text(
            json.dumps(
                {
                    "latest_run": run.to_dict(),
                    "runs": runs,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_daily_artifacts(self, run: ResearchAgentRun) -> Path:
        artifact_dir = self.artifact_root / f"daily_research_{run.run_id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        discussion_lines = [
            f"# 每日研究 Agent 讨论 {run.run_id}\n\n",
            f"- generated_at: {run.generated_at}\n",
            f"- mode: {run.mode}\n",
            f"- summary: {run.summary}\n\n",
        ]
        signal_lines: list[str] = []
        for suggestion in run.suggestions:
            discussion_lines.extend(
                [
                    f"## {suggestion.title}\n\n",
                    f"- target: {suggestion.target}\n",
                    f"- config_file: {suggestion.config_file}\n",
                    f"- rationale: {suggestion.rationale}\n",
                    f"- proposed_change: {suggestion.proposed_change}\n",
                ]
            )
            symbol = _symbol_from_target(suggestion.target)
            if not symbol:
                continue
            name = suggestion.target.replace(f"({symbol})", "").strip() or symbol
            evidence_hashes = sorted(
                {
                    stable_json_hash(asdict(item))
                    for item in suggestion.evidence + suggestion.counter_evidence
                }
            )
            if not evidence_hashes:
                evidence_hashes = [stable_json_hash(asdict(suggestion))]
            config_hash = file_content_hash(self.config_dir / suggestion.config_file)
            price_snapshot_hash = stable_json_hash(
                {
                    "source": "daily_research_agent",
                    "run_id": run.run_id,
                    "symbol": symbol,
                    "as_of_date": self.today.isoformat(),
                }
            )
            signal = merge_mgfs_agent_signals(
                symbol=symbol,
                name=name,
                as_of_date=self.today,
                signals=[
                    MGFSAgentSignal(
                        source="research_agent",
                        action="hold_review",
                        score=0.0,
                        confidence=suggestion.confidence,
                        rationale=suggestion.rationale,
                        evidence_hashes=evidence_hashes,
                        risk_flags=["requires_human_review"],
                    )
                ],
                weights={"research_agent": 1.0},
                config_hash=config_hash,
                price_snapshot_hash=price_snapshot_hash,
            )
            signal_lines.append(signal.to_json())

        (artifact_dir / "agent_discussion.md").write_text(
            "".join(discussion_lines),
            encoding="utf-8",
        )
        (artifact_dir / "mgfs_research_signal_v1.jsonl").write_text(
            "\n".join(signal_lines) + ("\n" if signal_lines else ""),
            encoding="utf-8",
        )
        (artifact_dir / "run_summary.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "run_id": run.run_id,
                    "decision_count": len(signal_lines),
                    "symbol_count": len(signal_lines),
                    "adapter_status": {
                        "point_in_time_inputs": "daily_research_snapshot",
                        "research_signal_schema": "mgfs_research_signal_v1",
                        "instruction_boundary": "research_only",
                    },
                    "borrowed_from": {
                        "repo": "utopia",
                        "patterns": ["agent_discussion", "research_signal_jsonl"],
                    },
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return artifact_dir

    def _read_payload(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {}
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _coerce_date(value: date | str | None) -> date:
        if value is None:
            return date.today()
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)


def _display_name(filename: str) -> str:
    names = {
        "policy_whitelist.yaml": "政策白名单",
        "ecosystem_themes.yaml": "生态主题",
        "moat_static_base.yaml": "护城河评分",
    }
    return names.get(filename, filename)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _signal_target(signal: dict[str, Any], key: str) -> str:
    values = signal.get(key, [])
    if not isinstance(values, list):
        return ""
    normalized = [str(item) for item in values if str(item).strip()]
    return "、".join(normalized)


def _symbol_from_target(target: str) -> str:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", target)
    return match.group(1) if match else ""


def _evidence_from_signal(signal: dict[str, Any]) -> EvidenceItem:
    published_at = str(signal.get("published_at") or "未知日期")
    url = str(signal.get("url") or "未提供链接")
    title = str(signal.get("title") or "外部信号")
    return EvidenceItem(
        source=str(signal.get("source") or "外部信号源"),
        title=title,
        detail=f"{published_at} · {title} · {url}",
        polarity=str(signal.get("polarity") or "supporting"),
    )


def _stable_id(*parts: str) -> str:
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]

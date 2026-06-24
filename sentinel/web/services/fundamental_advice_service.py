from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Protocol

import yaml

from sentinel.config import AppSettings


DIMENSION_LABELS = {
    "brand_premium": "品牌溢价",
    "franchise_barrier": "壁垒/牌照",
    "switching_cost": "切换成本",
    "network_effect": "网络效应",
    "cost_advantage": "成本优势",
}


@dataclass(frozen=True, slots=True)
class TradingAgentsEvidence:
    source: str
    title: str
    detail: str
    polarity: str = "supporting"


@dataclass(frozen=True, slots=True)
class TradingAgentsFundamentalReport:
    provider: str
    ticker: str
    summary: str
    dimension_scores: dict[str, float]
    confidence: float
    evidence: list[TradingAgentsEvidence]
    counter_evidence: list[TradingAgentsEvidence]
    raw_decision: str = ""


@dataclass(frozen=True, slots=True)
class FundamentalScoreProposal:
    dimension: str
    label: str
    config_file: str
    path: str
    current_score: float | None
    proposed_score: float
    confidence: float
    rationale: str


@dataclass(frozen=True, slots=True)
class FundamentalAdviceResult:
    symbol: str
    name: str | None
    market: str
    sector: str | None
    provider: str
    ticker: str
    status: str
    boundary: str
    summary: str
    evidence: list[TradingAgentsEvidence] = field(default_factory=list)
    counter_evidence: list[TradingAgentsEvidence] = field(default_factory=list)
    proposals: list[FundamentalScoreProposal] = field(default_factory=list)
    raw_decision: str = ""


class FundamentalAdviceRunner(Protocol):
    def run(
        self,
        *,
        symbol: str,
        name: str | None,
        market: str,
        sector: str | None,
    ) -> TradingAgentsFundamentalReport:
        ...


class TradingAgentsRunner:
    """Runtime adapter for TauricResearch/TradingAgents.

    The adapter is deliberately thin. It calls TradingAgents when installed and
    configured, then wraps the raw decision as traceable research input. A
    project-specific structured runner can replace this protocol later without
    changing the MGFS UI or YAML safety boundary.
    """

    def run(
        self,
        *,
        symbol: str,
        name: str | None,
        market: str,
        sector: str | None,
    ) -> TradingAgentsFundamentalReport:
        isolated_python = os.environ.get("TRADINGAGENTS_PYTHON")
        if isolated_python:
            return self._run_isolated(
                python_bin=isolated_python,
                symbol=symbol,
                name=name,
                market=market,
                sector=sector,
            )

        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except Exception as exc:  # pragma: no cover - depends on local install
            raise RuntimeError(
                "TradingAgents 未安装或不可导入；请先安装 TauricResearch/TradingAgents 并配置模型/API key"
            ) from exc

        ticker = _to_tradingagents_ticker(symbol=symbol, market=market)
        config = DEFAULT_CONFIG.copy()
        graph = TradingAgentsGraph(debug=False, config=config)
        _, decision = graph.propagate(ticker, date.today().isoformat())
        raw_decision = _stringify_decision(decision)

        return TradingAgentsFundamentalReport(
            provider="TradingAgents",
            ticker=ticker,
            summary=raw_decision[:800],
            dimension_scores={},
            confidence=0.45,
            evidence=[
                TradingAgentsEvidence(
                    source="TradingAgents raw decision",
                    title="多智能体基本面输出",
                    detail=raw_decision[:1200],
                )
            ],
            counter_evidence=[
                TradingAgentsEvidence(
                    source="MGFS 安全边界",
                    title="原始输出未结构化",
                    detail=(
                        "当前 TradingAgents 输出已作为研究证据收集，但没有结构化维度分，"
                        "因此不会生成可直接应用的 moat_static_base.yaml 分数变更。"
                    ),
                    polarity="counter",
                )
            ],
            raw_decision=raw_decision,
        )

    def _run_isolated(
        self,
        *,
        python_bin: str,
        symbol: str,
        name: str | None,
        market: str,
        sector: str | None,
    ) -> TradingAgentsFundamentalReport:
        helper = Path(
            os.environ.get("TRADINGAGENTS_HELPER_SCRIPT", _default_helper_script())
        )
        timeout = _tradingagents_timeout_seconds()
        cmd = [
            python_bin,
            str(helper),
            "--symbol",
            symbol,
            "--market",
            market,
            "--date",
            date.today().isoformat(),
        ]
        if name:
            cmd.extend(["--name", name])
        if sector:
            cmd.extend(["--sector", sector])

        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=str(_repo_root()),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"TradingAgents 运行超时（>{timeout} 秒），未生成评分建议"
            ) from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                "TradingAgents 隔离进程运行失败："
                + (detail[-1200:] if detail else "没有错误输出")
            )

        payload = _extract_json_payload(completed.stdout)
        return _report_from_payload(payload)


class FundamentalAdviceService:
    def __init__(
        self,
        config_dir: Path | str | None = None,
        runner: FundamentalAdviceRunner | None = None,
    ) -> None:
        settings = AppSettings()
        self.config_dir = (
            Path(config_dir) if config_dir is not None else settings.resolved_config_dir
        )
        self.runner = runner if runner is not None else TradingAgentsRunner()

    def generate(self, *, symbol: str, market: str) -> FundamentalAdviceResult:
        moat_data = self._load_moat_data()
        company = self._company_config(moat_data, symbol)
        name = _optional_str(company.get("name"))
        sector = _optional_str(company.get("sector"))

        try:
            report = self.runner.run(
                symbol=symbol,
                name=name,
                market=market,
                sector=sector,
            )
        except Exception as exc:
            return FundamentalAdviceResult(
                symbol=symbol,
                name=name,
                market=market,
                sector=sector,
                provider="TradingAgents",
                ticker=_to_tradingagents_ticker(symbol=symbol, market=market),
                status="unavailable",
                boundary="advisory_only",
                summary=_sanitize_unavailable_reason(str(exc)),
                counter_evidence=[
                    TradingAgentsEvidence(
                        source="系统边界",
                        title="未生成评分建议",
                        detail="TradingAgents 运行失败时不回退为臆测评分，也不会修改 YAML。",
                        polarity="counter",
                    )
                ],
            )

        proposals = self._build_proposals(
            symbol=symbol,
            company=company,
            report=report,
        )
        return FundamentalAdviceResult(
            symbol=symbol,
            name=name,
            market=market,
            sector=sector,
            provider=report.provider,
            ticker=report.ticker,
            status="completed",
            boundary="advisory_only",
            summary=report.summary,
            evidence=report.evidence,
            counter_evidence=report.counter_evidence,
            proposals=proposals,
            raw_decision=report.raw_decision,
        )

    def _build_proposals(
        self,
        *,
        symbol: str,
        company: dict[str, Any],
        report: TradingAgentsFundamentalReport,
    ) -> list[FundamentalScoreProposal]:
        base_score = company.get("base_score", {})
        if not isinstance(base_score, dict):
            base_score = {}

        proposals: list[FundamentalScoreProposal] = []
        for dimension, proposed in report.dimension_scores.items():
            proposed_score = _clamp_score(proposed)
            current_score = _current_dimension_score(base_score.get(dimension))
            rationale = (
                f"{report.provider} 建议将 {DIMENSION_LABELS.get(dimension, dimension)} "
                f"从 {current_score if current_score is not None else '未配置'} "
                f"复核到 {proposed_score:.1f}。"
            )
            proposals.append(
                FundamentalScoreProposal(
                    dimension=dimension,
                    label=DIMENSION_LABELS.get(dimension, dimension),
                    config_file="moat_static_base.yaml",
                    path=f"companies.{symbol}.base_score.{dimension}.score",
                    current_score=current_score,
                    proposed_score=proposed_score,
                    confidence=_clamp_confidence(report.confidence),
                    rationale=rationale,
                )
            )
        proposals.sort(key=lambda item: item.dimension)
        return proposals

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


def _to_tradingagents_ticker(*, symbol: str, market: str) -> str:
    if market == "A_SHARE":
        suffix = ".SS" if symbol.startswith("6") else ".SZ"
        return f"{symbol}{suffix}"
    if market == "HK":
        return f"{symbol.zfill(4)}.HK" if symbol.isdigit() else symbol
    return symbol


def _current_dimension_score(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("score")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _clamp_score(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 50.0
    return max(0.0, min(100.0, numeric))


def _clamp_confidence(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0.0, min(1.0, numeric))


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _stringify_decision(decision: Any) -> str:
    if isinstance(decision, str):
        return decision
    return repr(decision)


def _sanitize_unavailable_reason(message: str) -> str:
    text = message.strip()
    if "API key for provider" in text and "not set" in text:
        match = re.search(r"provider ['\"]([^'\"]+)['\"]", text)
        provider = match.group(1) if match else "当前模型"
        return (
            f"API key for provider '{provider}' is not set. "
            "请在本机安全环境中配置对应 provider 的 API key 后重试。"
        )
    return re.sub(r"\(e\.g\..*?\)", "", text).strip()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_helper_script() -> str:
    return str(_repo_root() / "scripts" / "run_tradingagents_fundamental.py")


def _tradingagents_timeout_seconds() -> int:
    raw = os.environ.get("TRADINGAGENTS_TIMEOUT_SECONDS", "240")
    try:
        timeout = int(raw)
    except ValueError:
        timeout = 240
    return max(30, timeout)


def _extract_json_payload(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError("TradingAgents 隔离进程没有返回 JSON 结果")


def _report_from_payload(payload: dict[str, Any]) -> TradingAgentsFundamentalReport:
    raw_scores = payload.get("dimension_scores", {})
    dimension_scores = {}
    if isinstance(raw_scores, dict):
        dimension_scores = {
            str(key): _clamp_score(value) for key, value in raw_scores.items()
        }
    return TradingAgentsFundamentalReport(
        provider=str(payload.get("provider") or "TradingAgents"),
        ticker=str(payload.get("ticker") or ""),
        summary=str(payload.get("summary") or ""),
        dimension_scores=dimension_scores,
        confidence=_clamp_confidence(payload.get("confidence", 0.45)),
        evidence=_evidence_from_payload(payload.get("evidence"), "supporting"),
        counter_evidence=_evidence_from_payload(
            payload.get("counter_evidence"), "counter"
        ),
        raw_decision=str(payload.get("raw_decision") or ""),
    )


def _evidence_from_payload(value: Any, default_polarity: str) -> list[TradingAgentsEvidence]:
    if not isinstance(value, list):
        return []
    evidence: list[TradingAgentsEvidence] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        evidence.append(
            TradingAgentsEvidence(
                source=str(item.get("source") or "TradingAgents"),
                title=str(item.get("title") or "未命名证据"),
                detail=str(item.get("detail") or ""),
                polarity=str(item.get("polarity") or default_polarity),
            )
        )
    return evidence

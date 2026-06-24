#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TauricResearch/TradingAgents and emit one JSON report."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", required=True)
    parser.add_argument("--name")
    parser.add_argument("--sector")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph
    except Exception as exc:
        print(f"TradingAgents import failed: {exc}", file=sys.stderr)
        return 2

    ticker = _to_tradingagents_ticker(symbol=args.symbol, market=args.market)
    config = DEFAULT_CONFIG.copy()
    try:
        graph = TradingAgentsGraph(debug=False, config=config)
        final_state, decision = graph.propagate(ticker, args.date)
    except Exception as exc:
        print(f"TradingAgents run failed for {ticker}: {exc}", file=sys.stderr)
        return 3

    raw_decision = _stringify_decision(decision)
    payload = {
        "provider": "TradingAgents",
        "ticker": ticker,
        "summary": raw_decision[:800],
        "dimension_scores": _dimension_scores_from_decision(decision),
        "confidence": _confidence_from_decision(decision),
        "evidence": _evidence_from_state(final_state, fallback=raw_decision),
        "counter_evidence": [
            {
                "source": "MGFS 安全边界",
                "title": "原始输出未结构化",
                "detail": (
                    "TradingAgents 输出会作为研究证据进入页面；只有当输出包含 "
                    "dimension_scores 时，才生成可追溯评分建议。"
                ),
                "polarity": "counter",
            }
        ],
        "raw_decision": raw_decision,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _to_tradingagents_ticker(*, symbol: str, market: str) -> str:
    if market == "A_SHARE":
        suffix = ".SS" if symbol.startswith("6") else ".SZ"
        return f"{symbol}{suffix}"
    if market == "HK":
        return f"{symbol.zfill(4)}.HK" if symbol.isdigit() else symbol
    return symbol


def _dimension_scores_from_decision(decision: Any) -> dict[str, float]:
    if isinstance(decision, dict):
        scores = decision.get("dimension_scores")
        if isinstance(scores, dict):
            return {
                str(key): float(value)
                for key, value in scores.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
    return {}


def _confidence_from_decision(decision: Any) -> float:
    if isinstance(decision, dict):
        confidence = decision.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            return max(0.0, min(1.0, float(confidence)))
    return 0.45


def _evidence_from_state(final_state: Any, *, fallback: str) -> list[dict[str, str]]:
    if not isinstance(final_state, dict):
        return [_raw_decision_evidence(fallback)]

    evidence: list[dict[str, str]] = []
    report_fields = [
        ("fundamentals_report", "Fundamentals Analyst", "基本面报告"),
        ("news_report", "News Analyst", "新闻/政策报告"),
        ("sentiment_report", "Sentiment Analyst", "情绪报告"),
        ("market_report", "Technical Analyst", "技术面报告"),
    ]
    for field, source, title in report_fields:
        detail = final_state.get(field)
        if isinstance(detail, str) and detail.strip():
            evidence.append(
                {"source": source, "title": title, "detail": detail.strip()[:1200]}
            )

    debate = final_state.get("investment_debate_state")
    if isinstance(debate, dict):
        manager_decision = debate.get("judge_decision")
        if isinstance(manager_decision, str) and manager_decision.strip():
            evidence.append(
                {
                    "source": "Research Manager",
                    "title": "研究经理裁决",
                    "detail": manager_decision.strip()[:1200],
                }
            )

    return evidence if evidence else [_raw_decision_evidence(fallback)]


def _raw_decision_evidence(raw_decision: str) -> dict[str, str]:
    return {
        "source": "TradingAgents raw decision",
        "title": "多智能体基本面输出",
        "detail": raw_decision[:1200],
    }


def _stringify_decision(decision: Any) -> str:
    if isinstance(decision, str):
        return decision
    try:
        return json.dumps(decision, ensure_ascii=False, default=str)
    except TypeError:
        return repr(decision)


if __name__ == "__main__":
    raise SystemExit(main())

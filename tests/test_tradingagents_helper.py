from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_helper_module():
    path = Path("scripts/run_tradingagents_fundamental.py").resolve()
    spec = importlib.util.spec_from_file_location("run_tradingagents_fundamental", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_helper_builds_traceable_evidence_from_tradingagents_final_state():
    helper = _load_helper_module()
    final_state = {
        "fundamentals_report": "基本面分析正文",
        "news_report": "新闻分析正文",
        "sentiment_report": "情绪分析正文",
        "market_report": "技术面分析正文",
        "investment_debate_state": {
            "judge_decision": "研究经理裁决正文",
        },
    }

    evidence = helper._evidence_from_state(final_state, fallback="最终决策正文")

    assert [item["source"] for item in evidence] == [
        "Fundamentals Analyst",
        "News Analyst",
        "Sentiment Analyst",
        "Technical Analyst",
        "Research Manager",
    ]
    assert evidence[0]["title"] == "基本面报告"
    assert evidence[0]["detail"] == "基本面分析正文"

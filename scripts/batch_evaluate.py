#!/usr/bin/env python3
"""Batch evaluation script for MGFS — CSI 300 stress testing.

Usage:
    PYTHONPATH=/path/to/project python scripts/batch_evaluate.py \
        --stock-list data/csi300_cons.csv \
        --output reports/csi300_eval_$(date +%Y%m%d).csv

Without --stock-list, uses a built-in mock universe for dry-run testing.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Allow running from project root
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.mgfs.config_loader import build_orchestrator, load_mgfs_config
from sentinel.mgfs.factor_plugin import TargetInfo

logger = logging.getLogger(__name__)

# Mock universe for dry-run testing (symbol, name, sector)
_MOCK_UNIVERSE: list[tuple[str, str, str]] = [
    ("600519", "贵州茅台", "白酒"),
    ("000858", "五粮液", "白酒"),
    ("000001", "平安银行", "银行"),
    ("600036", "招商银行", "银行"),
    ("601899", "紫金矿业", "有色金属"),
    ("600028", "中国石化", "煤炭"),
    ("601318", "中国平安", "保险"),
    ("000002", "万科A", "房地产"),
    ("002594", "比亚迪", "新能源汽车"),
    ("300750", "宁德时代", "新能源汽车"),
    ("600276", "恒瑞医药", "医药"),
    ("000568", "泸州老窖", "白酒"),
    ("601012", "隆基绿能", "新能源"),
    ("600887", "伊利股份", "食品饮料"),
    ("000063", "中兴通讯", "通信"),
]


def load_stock_list(path: Path | None) -> list[tuple[str, str, str]]:
    """Load stock list from CSV or return mock universe."""
    if path is None:
        logger.info("No stock list provided, using mock universe (%d stocks)", len(_MOCK_UNIVERSE))
        return _MOCK_UNIVERSE

    stocks: list[tuple[str, str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row.get("symbol", "").strip()
            name = row.get("name", "").strip()
            sector = row.get("sector", "").strip()
            if symbol:
                stocks.append((symbol, name, sector))
    logger.info("Loaded %d stocks from %s", len(stocks), path)
    return stocks


def evaluate_single(
    orchestrator: Any,
    symbol: str,
    name: str,
    sector: str,
    policy: str = "neutral",
) -> dict[str, Any]:
    """Evaluate a single stock and return flat result dict."""
    target = TargetInfo(
        symbol=symbol,
        market=Market.A_SHARE,
        asset_class="equity",
        name=name,
        sector=sector if sector else None,
    )
    decision = orchestrator.evaluate(target, policy_rating=policy)

    # Flatten factor scores
    moat_score = decision.factor_scores.get("moat", None)
    valuation_score = decision.factor_scores.get("valuation", None)
    policy_score = decision.factor_scores.get("policy", None)

    result: dict[str, Any] = {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "policy_rating": policy,
        "raw_total": decision.raw_total,
        "final_score": decision.final_score,
        "rating": decision.rating,
        "action": decision.action,
        "alert_level": decision.alert_level.value,
        "overall_confidence": decision.report_sections.get("overall_confidence"),
        "watermark": decision.report_sections.get("watermark", ""),
        "circuit_breakers_triggered": len(decision.circuit_breakers_triggered),
        "moat_score": moat_score.score if moat_score else None,
        "moat_confidence": moat_score.confidence if moat_score else None,
        "valuation_score": valuation_score.score if valuation_score else None,
        "valuation_confidence": valuation_score.confidence if valuation_score else None,
        "valuation_percentile": (
            valuation_score.details.get("primary_percentile")
            if valuation_score
            else None
        ),
        "valuation_zone": (
            valuation_score.details.get("zone")
            if valuation_score
            else None
        ),
        "valuation_metric": (
            valuation_score.details.get("primary_metric")
            if valuation_score
            else None
        ),
        "policy_score": policy_score.score if policy_score else None,
    }
    return result


def print_summary(results: list[dict[str, Any]]) -> None:
    """Print rating distribution and key stats."""
    total = len(results)
    if total == 0:
        print("No results.")
        return

    ratings: dict[str, int] = {}
    alert_levels: dict[str, int] = {}
    zones: dict[str, int] = {}
    circuit_triggered = 0
    low_confidence = 0

    for r in results:
        ratings[r["rating"]] = ratings.get(r["rating"], 0) + 1
        alert_levels[r["alert_level"]] = alert_levels.get(r["alert_level"], 0) + 1
        if r["valuation_zone"]:
            zones[r["valuation_zone"]] = zones.get(r["valuation_zone"], 0) + 1
        if r["circuit_breakers_triggered"] > 0:
            circuit_triggered += 1
        if r["overall_confidence"] is not None and r["overall_confidence"] < 0.5:
            low_confidence += 1

    print("\n" + "=" * 60)
    print("《MGFS 批量评估压力测试报告》")
    print(f"评估时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"样本总数: {total}")
    print("=" * 60)

    print("\n【评级分布】")
    for rating, count in sorted(ratings.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        bar = "█" * int(pct / 2)
        print(f"  {rating:12s}: {count:3d} ({pct:5.1f}%) {bar}")

    print("\n【告警级别分布】")
    for level, count in sorted(alert_levels.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        print(f"  {level:15s}: {count:3d} ({pct:5.1f}%)")

    print("\n【估值击球区分布】")
    for zone, count in sorted(zones.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        print(f"  {zone:12s}: {count:3d} ({pct:5.1f}%)")

    print("\n【关键指标】")
    print(f"  触发熔断: {circuit_triggered}/{total} ({circuit_triggered/total*100:.1f}%)")
    print(f"  低置信度 (<0.5): {low_confidence}/{total} ({low_confidence/total*100:.1f}%)")

    # Calibration advice
    hard_veto_pct = alert_levels.get("hard_veto", 0) / total * 100
    soft_veto_pct = alert_levels.get("soft_veto", 0) / total * 100
    strong_buy_pct = ratings.get("Strong Buy", 0) / total * 100

    print("\n【阈值校准建议】")
    if hard_veto_pct > 30:
        print(f"  ⚠️  hard_veto 占比 {hard_veto_pct:.1f}% — 阈值过于苛刻，建议放宽")
    elif hard_veto_pct < 5:
        print(f"  ⚠️  hard_veto 占比 {hard_veto_pct:.1f}% — 阈值过于宽松，建议收紧")
    else:
        print(f"  ✅ hard_veto 占比 {hard_veto_pct:.1f}% — 合理区间")

    if strong_buy_pct > 30:
        print(f"  ⚠️  Strong Buy 占比 {strong_buy_pct:.1f}% — 买入信号过于泛滥")
    elif strong_buy_pct < 3:
        print(f"  ⚠️  Strong Buy 占比 {strong_buy_pct:.1f}% — 买入信号过于稀缺")
    else:
        print(f"  ✅ Strong Buy 占比 {strong_buy_pct:.1f}% — 合理区间")

    print("=" * 60)


def write_csv(results: list[dict[str, Any]], path: Path) -> None:
    """Write results to CSV."""
    if not results:
        return
    fieldnames = list(results[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    logger.info("CSV report written to %s", path)


def main() -> int:
    parser = argparse.ArgumentParser(description="MGFS Batch Evaluation — CSI 300 Stress Test")
    parser.add_argument("--stock-list", type=Path, help="CSV file with columns: symbol,name,sector")
    parser.add_argument("--output", type=Path, default=Path("reports/batch_eval.csv"), help="Output CSV path")
    parser.add_argument("--policy", default="neutral", help="Policy rating to apply")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of stocks (0 = all)")
    parser.add_argument("--demo-moat-score", type=float, default=0, help="Demo mode: use this score when moat data is missing (0 = disabled)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Load orchestrator
    settings = AppSettings()
    config_path = settings.resolved_config_dir / "mgfs_config.yaml"
    if not config_path.exists():
        logger.error("mgfs_config.yaml not found at %s", config_path)
        return 1

    config = load_mgfs_config(config_path)
    from sentinel.mgfs.data.eastmoney_fetcher import EastmoneyValuationFetcher

    fetchers = {"valuation": EastmoneyValuationFetcher()}
    plugin_kwargs: dict[str, dict[str, Any]] = {}
    if args.demo_moat_score > 0:
        plugin_kwargs["moat"] = {"fallback_score": args.demo_moat_score}
        logger.info("Demo mode: using fallback moat score %.1f", args.demo_moat_score)
    orchestrator = build_orchestrator(
        config,
        config_dir=settings.resolved_config_dir,
        fetchers=fetchers,
        plugin_kwargs=plugin_kwargs,
    )
    logger.info("Orchestrator loaded with plugins: %s", list(orchestrator.plugins.keys()))

    # Load stock universe
    stocks = load_stock_list(args.stock_list)
    if args.limit > 0:
        stocks = stocks[:args.limit]

    # Evaluate each stock
    results: list[dict[str, Any]] = []
    for i, (symbol, name, sector) in enumerate(stocks, 1):
        logger.info("[%d/%d] Evaluating %s %s (%s)", i, len(stocks), symbol, name, sector)
        try:
            result = evaluate_single(orchestrator, symbol, name, sector, args.policy)
            results.append(result)
        except Exception:
            logger.exception("Failed to evaluate %s", symbol)
            results.append({
                "symbol": symbol,
                "name": name,
                "sector": sector,
                "rating": "Error",
                "action": "评估失败",
                "alert_level": "yellow_warning",
            })

    # Output
    print_summary(results)
    write_csv(results, args.output)

    # Also write JSON summary
    summary_path = args.output.with_suffix(".summary.json")
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_stocks": len(stocks),
        "successful_evaluations": len([r for r in results if r.get("rating") != "Error"]),
        "rating_distribution": {k: v for k, v in sorted(
            {r["rating"]: sum(1 for x in results if x.get("rating") == r["rating"]) for r in results}.items(),
            key=lambda x: -x[1]
        )},
        "alert_distribution": {k: v for k, v in sorted(
            {r.get("alert_level", "unknown"): sum(1 for x in results if x.get("alert_level") == r.get("alert_level")) for r in results}.items(),
            key=lambda x: -x[1]
        )},
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info("Summary JSON written to %s", summary_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())

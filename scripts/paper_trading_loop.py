#!/usr/bin/env python3
"""Paper Trading Loop — Daily automated evaluation for core stock pool."""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.mgfs.config_loader import build_orchestrator, load_mgfs_config
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.publishers.mgfs_report import MGFSReportPublisher, build_text_report

logger = logging.getLogger(__name__)

CORE_POOL_PATH = Path("data/core_pool.csv")
REPORT_DIR = Path("reports/paper_trading")


def load_core_pool(path: Path = CORE_POOL_PATH) -> list[tuple[str, str, str]]:
    stocks: list[tuple[str, str, str]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row.get("symbol", "").strip()
            name = row.get("name", "").strip()
            sector = row.get("sector", "").strip()
            if symbol:
                stocks.append((symbol, name, sector))
    logger.info("Loaded core pool: %d stocks from %s", len(stocks), path)
    return stocks


def evaluate_pool(
    orchestrator: Any,
    stocks: list[tuple[str, str, str]],
    policy: str = "neutral",
) -> tuple[list[dict[str, Any]], list[Any]]:
    results: list[dict[str, Any]] = []
    decisions: list[Any] = []

    for i, (symbol, name, sector) in enumerate(stocks, 1):
        logger.info("[%d/%d] Evaluating %s %s (%s)", i, len(stocks), symbol, name, sector)
        target = TargetInfo(
            symbol=symbol,
            market=Market.A_SHARE,
            asset_class="equity",
            name=name,
            sector=sector if sector else None,
        )
        try:
            decision = orchestrator.evaluate(target, policy_rating=policy)
            decisions.append(decision)
            results.append({
                "symbol": symbol,
                "name": name,
                "sector": sector,
                "rating": decision.rating,
                "action": decision.action,
                "final_score": decision.final_score,
                "alert_level": decision.alert_level.value,
            })
        except Exception:
            logger.exception("Failed to evaluate %s", symbol)
            results.append({
                "symbol": symbol,
                "name": name,
                "sector": sector,
                "rating": "Error",
                "action": "评估失败",
                "final_score": 0.0,
                "alert_level": "yellow_warning",
            })

    return results, decisions


def build_summary_report(
    results: list[dict[str, Any]],
    decisions: list[Any],
    timestamp: datetime,
) -> str:
    total = len(results)
    if total == 0:
        return "无评估结果。"

    ratings: dict[str, int] = {}
    alerts: dict[str, int] = {}
    strong_buy_candidates: list[str] = []
    hard_veto_list: list[str] = []

    for r in results:
        ratings[r["rating"]] = ratings.get(r["rating"], 0) + 1
        alerts[r["alert_level"]] = alerts.get(r["alert_level"], 0) + 1
        if r["rating"] == "Strong Buy":
            strong_buy_candidates.append("{} {}".format(r["symbol"], r["name"]))
        if r["alert_level"] == "hard_veto":
            hard_veto_list.append("{} {}".format(r["symbol"], r["name"]))

    lines = [
        "📊 MGFS 模拟盘日报 | {}".format(timestamp.strftime("%Y-%m-%d %H:%M")),
        "评估标的: {} 只（核心股票池）".format(total),
        "",
        "【评级分布】",
    ]
    for rating, count in sorted(ratings.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        lines.append("  {}: {}只 ({:.1f}%)".format(rating, count, pct))

    lines.append("")
    lines.append("【告警分布】")
    for level, count in sorted(alerts.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        lines.append("  {}: {}只 ({:.1f}%)".format(level, count, pct))

    if strong_buy_candidates:
        lines.append("")
        lines.append("🟢 【Strong Buy 信号】")
        for s in strong_buy_candidates:
            lines.append("  {}".format(s))

    if hard_veto_list:
        lines.append("")
        lines.append("🔴 【Hard Veto 一票否决】")
        for s in hard_veto_list[:5]:
            lines.append("  {}".format(s))
        if len(hard_veto_list) > 5:
            lines.append("  ... 等共 {} 只".format(len(hard_veto_list)))

    sorted_results = sorted(
        [r for r in results if r["rating"] not in ("Error",)],
        key=lambda x: x["final_score"],
        reverse=True,
    )
    if sorted_results:
        lines.append("")
        lines.append("🏆 【评分前三】")
        for r in sorted_results[:3]:
            lines.append(
                "  {} {} | {} | {:.1f}分".format(
                    r["symbol"], r["name"], r["rating"], r["final_score"]
                )
            )

    lines.append("")
    lines.append("— MGFS 价值投资决策系统")
    return "\n".join(lines)


def save_reports(
    results: list[dict[str, Any]],
    decisions: list[Any],
    timestamp: datetime,
) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = timestamp.strftime("%Y%m%d_%H%M")

    csv_path = REPORT_DIR / "paper_trading_{}.csv".format(date_str)
    if results:
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)
        logger.info("CSV saved: %s", csv_path)

    txt_path = REPORT_DIR / "paper_trading_{}.txt".format(date_str)
    with txt_path.open("w", encoding="utf-8") as f:
        f.write("MGFS Paper Trading Report | {}\n".format(timestamp))
        f.write("=" * 50 + "\n\n")
        for decision in decisions:
            f.write(build_text_report(decision))
            f.write("\n\n")
    logger.info("Text report saved: %s", txt_path)

    return csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description="MGFS Paper Trading Loop")
    parser.add_argument("--dry-run", action="store_true", help="Console only, no Feishu push")
    parser.add_argument("--pool", type=Path, default=CORE_POOL_PATH, help="Core stock pool CSV")
    parser.add_argument("--policy", default="neutral", help="Policy rating")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    timestamp = datetime.now()
    logger.info("=== Paper Trading Loop Started | %s ===", timestamp.strftime("%Y-%m-%d %H:%M"))

    settings = AppSettings()
    config_path = settings.resolved_config_dir / "mgfs_config.yaml"
    if not config_path.exists():
        logger.error("mgfs_config.yaml not found at %s", config_path)
        return 1

    config = load_mgfs_config(config_path)
    from sentinel.mgfs.data.eastmoney_fetcher import EastmoneyValuationFetcher

    fetchers = {"valuation": EastmoneyValuationFetcher()}
    orchestrator = build_orchestrator(
        config,
        config_dir=settings.resolved_config_dir,
        fetchers=fetchers,
    )
    logger.info("Orchestrator ready with plugins: %s", list(orchestrator.plugins.keys()))

    stocks = load_core_pool(args.pool)
    if not stocks:
        logger.error("Core pool is empty")
        return 1

    results, decisions = evaluate_pool(orchestrator, stocks, args.policy)

    summary = build_summary_report(results, decisions, timestamp)
    print("\n" + summary + "\n")

    csv_path = save_reports(results, decisions, timestamp)

    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL")
    if args.dry_run:
        logger.info("Dry run mode — skipping Feishu push")
    elif not webhook_url:
        logger.warning("FEISHU_WEBHOOK_URL not set — skipping Feishu push")
    else:
        publisher = MGFSReportPublisher(webhook_url=webhook_url)
        published = 0
        for decision in decisions:
            if decision.rating in ("Strong Buy", "Accumulate") or decision.alert_level.value == "hard_veto":
                try:
                    publisher.publish(decision)
                    published += 1
                except Exception:
                    logger.exception("Failed to publish %s", decision.target.symbol)
        logger.info("Published %d alerts to Feishu", published)

    logger.info("=== Paper Trading Loop Complete | CSV: %s ===", csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

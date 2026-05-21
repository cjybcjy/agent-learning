from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sentinel.config import AppSettings
from sentinel.mgfs.evolution.bayes_calibrator import BayesCalibrator, CalibrationReport
from sentinel.mgfs.evolution.batch_backtest import BatchBacktest

logger = logging.getLogger(__name__)

EASTMONEY_CACHE_DIR = Path.home() / ".cache" / "sentinel" / "eastmoney"


def _load_eastmoney_cache(
    raw_data: list[dict[str, Any]],
    start_date: date,
    end_date: date,
) -> dict[date, float]:
    """Parse Eastmoney K-line JSON and filter to date range."""
    prices: dict[date, float] = {}
    for row in raw_data:
        date_str = row.get("TRADE_DATE", "")
        if not date_str:
            continue
        # Parse "2025-01-02 00:00:00" or "2025-01-02"
        trade_date = datetime.strptime(date_str.split()[0], "%Y-%m-%d").date()
        if start_date <= trade_date <= end_date:
            prices[trade_date] = float(row.get("CLOSE_PRICE", 0.0))
    return prices


def _load_yaml_scores(yaml_path: Path | None) -> dict[str, float]:
    """Load static moat scores from YAML config."""
    if yaml_path is None or not yaml_path.exists():
        return {}
    import yaml

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    companies = data.get("companies", {})
    scores: dict[str, float] = {}
    for symbol, cfg in companies.items():
        cfg = cfg or {}
        base = cfg.get("base_score")
        if isinstance(base, dict):
            # Average across moat dimensions (brand_premium, franchise_barrier, etc.)
            dim_scores = [
                v["score"] for v in base.values()
                if isinstance(v, dict) and "score" in v
            ]
            scores[symbol] = sum(dim_scores) / len(dim_scores) if dim_scores else 50.0
        elif isinstance(base, (int, float)):
            scores[symbol] = float(base)
        else:
            scores[symbol] = 50.0
    return scores


def _run_backtest(
    *,
    symbols: list[str],
    price_loaders: dict[str, dict[date, float]],
    evaluators: dict[str, dict[date, float]],
    static_scores: dict[str, float],
    names: dict[str, str],
    start_date: date,
    end_date: date,
    min_samples: int = 30,
) -> list[CalibrationReport]:
    """Execute batch backtest and return calibration reports."""
    calibrator = BayesCalibrator(min_samples=min_samples)
    batch = BatchBacktest(
        start_date=start_date,
        end_date=end_date,
        calibrator=calibrator,
    )
    return batch.run(
        symbols=symbols,
        price_loaders=price_loaders,
        evaluators=evaluators,
        static_scores=static_scores,
        names=names,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MGFS 2.0 历史沙盘回溯 — 贝叶斯校准环",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="回测起点 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="回测终点 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        required=True,
        help="逗号分隔的股票代码列表 (如 600519,300750)",
    )
    parser.add_argument(
        "--score-file",
        type=str,
        default=None,
        help="静态评分 YAML 文件路径 (默认: config/moat_static_base.yaml)",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=str(EASTMONEY_CACHE_DIR),
        help="Eastmoney K 线缓存目录",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=30,
        help="最小样本天数 (默认 30)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出文件路径 (默认打印到 stdout)",
    )
    args = parser.parse_args(argv)

    start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    symbols = [s.strip() for s in args.symbols.split(",")]
    cache_dir = Path(args.cache_dir)

    # Load static scores
    if args.score_file:
        score_path = Path(args.score_file)
    else:
        settings = AppSettings()
        score_path = settings.resolved_config_dir / "moat_static_base.yaml"
    static_scores = _load_yaml_scores(score_path)

    # Load price data from Eastmoney cache
    price_loaders: dict[str, dict[date, float]] = {}
    evaluators: dict[str, dict[date, float]] = {}
    names: dict[str, str] = {}

    for symbol in symbols:
        # Find the most recent cache file for this symbol
        cache_files = sorted(cache_dir.glob(f"{symbol}_all_*.json"))
        if not cache_files:
            logger.warning("No cache found for %s, skipping", symbol)
            continue

        latest_cache = cache_files[-1]
        try:
            raw_data = json.loads(latest_cache.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse cache for %s: %s", symbol, exc)
            continue

        prices = _load_eastmoney_cache(raw_data, start, end)
        if not prices:
            logger.warning("No price data in range for %s, skipping", symbol)
            continue

        price_loaders[symbol] = prices
        # Use static score as daily evaluator score for simplicity
        score = static_scores.get(symbol, 50.0)
        evaluators[symbol] = {d: score for d in prices}
        names[symbol] = symbol  # Could lookup from cache SECUCODE if needed

    if not price_loaders:
        logger.error("No valid price data loaded for any symbol")
        return 1

    # Run backtest
    reports = _run_backtest(
        symbols=list(price_loaders.keys()),
        price_loaders=price_loaders,
        evaluators=evaluators,
        static_scores=static_scores,
        names=names,
        start_date=start,
        end_date=end,
        min_samples=args.min_samples,
    )

    if not reports:
        print("无可校准标的 (样本不足或无买入信号)")
        return 0

    # Format output
    lines: list[str] = []
    lines.append(f"MGFS 2.0 贝叶斯校准报告 ({start} → {end})")
    lines.append("=" * 90)
    lines.append(
        f"{'标的':<10} {'名称':<10} {'静态分':>8} {'建议分':>8} {'惩罚':>8} "
        f"{'置信度':>8} {'原因':<30}"
    )
    lines.append("-" * 90)

    for r in reports:
        suggested = f"{r.suggested_score:.1f}" if r.suggested_score is not None else "N/A"
        lines.append(
            f"{r.symbol:<10} {r.name:<10} {r.static_score:>8.1f} {suggested:>8} "
            f"{r.bias_penalty:>+8.2f} {r.confidence:>8.2f} {r.reason:<30}"
        )

    output = "\n".join(lines)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"报告已保存至 {args.output}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())

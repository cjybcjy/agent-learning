#!/usr/bin/env python3
"""Seed demo data with buy/sell factors for demonstration purposes."""

import asyncio
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heatmap.store.dao import Store, RawMessage, Mention

DEMO_MESSAGES = [
    # Crypto messages — across multiple platforms for multi-source demo
    ("BTC", "crypto", "BTC just broke $70k! Institutional buying accelerating.", "telegram"),
    ("BTC", "crypto", "Bitcoin ETF inflows hit record high today, bullish signal.", "coingecko"),
    ("BTC", "crypto", "PlanB says S2F model still on track for $100k this year.", "telegram"),
    ("BTC", "crypto", "BTC dominance rising, altcoins underperforming.", "discord"),
    ("ETH", "crypto", "Ethereum staking rewards looking attractive after upgrade.", "telegram"),
    ("ETH", "crypto", "ETH/BTC ratio at historic lows, potential reversal coming?", "coingecko"),
    ("ETH", "crypto", "Vitalik proposes new gas fee structure, community reacts.", "discord"),
    ("SOL", "crypto", "Solana network uptime improving, DeFi TVL climbing back.", "coingecko"),
    ("SOL", "crypto", "SOL price action strong after latest partnership announcement.", "telegram"),
    ("DOGE", "crypto", "Doge trending on Twitter again, memecoin season back?", "discord"),
    ("DOGE", "crypto", "Elon mentions dogecoin in latest tweet, price pumps 5%.", "telegram"),
    # A-share messages — xueqiu + eastmoney sources
    ("贵州茅台", "a_share", "茅台Q1业绩超预期，机构上调目标价至2200元。", "xueqiu"),
    ("贵州茅台", "a_share", "白酒板块回暖，茅台批发价企稳反弹。", "eastmoney"),
    ("贵州茅台", "a_share", "北向资金大幅加仓茅台，单日净买入超10亿。", "xueqiu"),
    ("贵州茅台", "a_share", "飞天茅台终端零售价重返2800元上方。", "eastmoney"),
    ("宁德时代", "a_share", "宁德时代新电池技术发布，能量密度提升15%。", "xueqiu"),
    ("宁德时代", "a_share", "新能源车销量超预期，电池龙头受益明显。", "eastmoney"),
    ("宁德时代", "a_share", "宁德时代海外工厂投产，全球化布局加速。", "xueqiu"),
    ("比亚迪", "a_share", "比亚迪5月销量再创新高，月度突破30万辆。", "eastmoney"),
    ("比亚迪", "a_share", "比亚迪海豹出口欧洲，品牌国际化提速。", "xueqiu"),
    ("比亚迪", "a_share", "比亚迪仰望U8交付量超预期，高端化战略见效。", "eastmoney"),
    # HK market
    ("腾讯控股", "hk", "腾讯游戏业务回暖，Q2营收预期上调。", "aastocks"),
    ("腾讯控股", "hk", "微信视频号商业化加速，广告收入增长强劲。", "futu"),
    ("阿里巴巴", "hk", "阿里云分拆上市计划推进，估值重塑预期升温。", "aastocks"),
    ("阿里巴巴", "hk", "蚂蚁集团整改完成，监管压力解除利好阿里。", "futu"),
    # US market
    ("NVDA", "us", "NVIDIA reports blowout earnings, AI chip demand surges.", "reddit"),
    ("NVDA", "us", "NVDA DD: Blackwell architecture analysis — 4x performance gain.", "stocktwits"),
    ("GME", "us", "GameStop announces strategic pivot into Web3 gaming.", "reddit"),
    ("TSLA", "us", "Tesla FSD v13 rolling out next month, robotaxi timeline on track.", "stocktwits"),
]


def _pick_alpha(symbol: str) -> float:
    """Generate a plausible buy/sell pressure score."""
    # Seed deterministically per symbol for consistency
    rng = random.Random(hash(symbol) & 0x7FFFFFFF)
    alpha = round(rng.uniform(-3.0, 5.0), 1)
    return alpha


async def seed():
    db_path = Path(__file__).resolve().parent.parent / "data" / "heatmap.db"
    store = Store(db_path)
    await store.init()

    try:
        base_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

        # Generate messages across today and yesterday for alpha computation
        today = base_time
        yesterday = base_time - timedelta(days=1)

        total = 0
        for i, (symbol, market, content, platform) in enumerate(DEMO_MESSAGES):
            # Spread: 60% today, 40% yesterday (creates growth → positive alpha)
            use_yesterday = i % 5 >= 2
            day = yesterday if use_yesterday else today
            posted_at = day + timedelta(minutes=(i % 30) * 5)

            msg = RawMessage(
                platform=platform,
                channel="seed",
                author_id=f"demo_user_{i}",
                content=content,
                posted_at=posted_at,
                fetched_at=datetime.now(timezone.utc),
                market=market,
            )
            mid = await store.insert_message(msg)
            await store.insert_mentions([
                Mention(mid, symbol, symbol, False, 1.0),
            ])
            total += 1

        print(f"Seeded {total} demo messages across today and yesterday")

        # Run daily scoring pipeline to compute alpha/beta
        from heatmap.aggregator.pipeline import run_daily_aggregation
        from heatmap.config import load_thresholds

        config_dir = Path(__file__).resolve().parent.parent / "config"
        thresholds = load_thresholds(config_dir / "thresholds.yaml")

        today_str = today.date().isoformat()
        yesterday_str = yesterday.date().isoformat()

        # Run for both days so yesterday has data for today's alpha comparison
        for date_str in [yesterday_str, today_str]:
            top = await run_daily_aggregation(
                store,
                date_str,
                alpha_min=thresholds.alpha_min,
                beta_min=thresholds.beta_min,
                stage_a_top_n=thresholds.stage_a_top_n,
                stage_b_top_n=thresholds.stage_b_top_n,
            )
            print(f"Daily aggregation for {date_str}: {len(top)} top candidates")

        # Run rollup for 30min windows
        from heatmap.aggregator.rollup import RollupEngine
        engine = RollupEngine(store)

        windows = [
            base_time - timedelta(hours=2),
            base_time - timedelta(hours=1, minutes=30),
            base_time - timedelta(hours=1),
            base_time - timedelta(minutes=30),
        ]
        for window in windows:
            ws = window.isoformat().replace("+00:00", "Z")
            we = (window + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
            await engine.compute_rollup_30min(ws, we)

        # Run 4h and daily rollups
        for window in windows:
            if window.minute == 0 and window.hour % 4 == 0:
                h4_start = window.isoformat().replace("+00:00", "Z")
                await engine.compute_rollup_4h(h4_start)

        await engine.compute_rollup_daily(today_str)
        print(f"Rollups complete for all windows")

        print("\nDemo data ready with buy/sell factors!")
        print("Check http://localhost:8000/ for the heatmap")

    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(seed())

#!/usr/bin/env python3
"""Seed demo data into the heatmap database for demonstration purposes."""

import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heatmap.store.dao import Store, RawMessage, Mention

DEMO_MESSAGES = [
    # Crypto messages
    ("BTC", "crypto", "BTC just broke $70k! Institutional buying accelerating."),
    ("BTC", "crypto", "Bitcoin ETF inflows hit record high today, bullish signal."),
    ("BTC", "crypto", "PlanB says S2F model still on track for $100k this year."),
    ("ETH", "crypto", "Ethereum staking rewards looking attractive after upgrade."),
    ("ETH", "crypto", "ETH/BTC ratio at historic lows, potential reversal coming?"),
    ("ETH", "crypto", "Vitalik proposes new gas fee structure, community reacts."),
    ("SOL", "crypto", "Solana network uptime improving, DeFi TVL climbing back."),
    ("SOL", "crypto", "SOL price action strong after latest partnership announcement."),
    ("DOGE", "crypto", "Doge trending on Twitter again, memecoin season back?"),
    ("DOGE", "crypto", "Elon mentions dogecoin in latest tweet, price pumps 5%."),
    # A-share messages
    ("茅台", "a_share", "茅台Q1业绩超预期，机构上调目标价至2200元。"),
    ("茅台", "a_share", "白酒板块回暖，茅台批发价企稳反弹。"),
    ("茅台", "a_share", "北向资金大幅加仓茅台，单日净买入超10亿。"),
    ("宁德时代", "a_share", "宁德时代新电池技术发布，能量密度提升15%。"),
    ("宁德时代", "a_share", "新能源车销量超预期，电池龙头受益明显。"),
    ("宁德时代", "a_share", "宁德时代海外工厂投产，全球化布局加速。"),
    ("比亚迪", "a_share", "比亚迪5月销量再创新高，月度突破30万辆。"),
    ("比亚迪", "a_share", "比亚迪海豹出口欧洲，品牌国际化提速。"),
    ("腾讯", "hk", "腾讯游戏业务回暖，Q2营收预期上调。"),
    ("腾讯", "hk", "微信视频号商业化加速，广告收入增长强劲。"),
]


async def seed():
    db_path = Path(__file__).resolve().parent.parent / "data" / "heatmap.db"
    store = Store(db_path)
    await store.init()

    try:
        # Generate messages across multiple 30min windows
        base_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        windows = [
            base_time - timedelta(hours=2),
            base_time - timedelta(hours=1, minutes=30),
            base_time - timedelta(hours=1),
            base_time - timedelta(minutes=30),
        ]

        total = 0
        for i, (symbol, market, content) in enumerate(DEMO_MESSAGES):
            window = windows[i % len(windows)]
            posted_at = window + timedelta(minutes=(i % 20) + 1)

            msg = RawMessage(
                platform="demo",
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

        print(f"Seeded {total} demo messages")

        # Run rollup for each window
        from heatmap.aggregator.rollup import RollupEngine
        engine = RollupEngine(store)

        for window in windows:
            ws = window.isoformat().replace("+00:00", "Z")
            we = (window + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
            await engine.compute_rollup_30min(ws, we)
            print(f"Rolled up window {ws}")

        print("\nDemo data ready!")
        print("Check http://localhost:8000/ for the heatmap")

    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(seed())

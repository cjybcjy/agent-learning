"""扫描近 30 天 raw_messages，对未命中任何 symbol 的高频词产出别名候选。
v1 仅产出 data/alias_suggestions.csv，等待人工审核。
"""
import asyncio
import csv
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiosqlite

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "heatmap.db"
OUT = ROOT / "data" / "alias_suggestions.csv"

WORD_RE = re.compile(r"[A-Za-z]{3,15}|[\u4e00-\u9fa5]{2,6}")

async def main():
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    counter: Counter[str] = Counter()
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT r.content FROM raw_messages r "
            "LEFT JOIN mentions m ON m.message_id = r.id "
            "WHERE m.id IS NULL AND r.posted_at >= ?", (cutoff,)
        ) as cur:
            async for (content,) in cur:
                for w in WORD_RE.findall(content or ""):
                    counter[w.lower()] += 1
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["candidate", "frequency"])
        for word, freq in counter.most_common(200):
            w.writerow([word, freq])
    print(f"wrote {OUT}")

if __name__ == "__main__":
    asyncio.run(main())

import math
from datetime import datetime, timedelta

from heatmap.store.dao import Store
from heatmap.aggregator.scoring import weighted_score
from heatmap.aggregator.gates import Candidate, compute_alpha_beta, select_top


def _prev_day(date: str) -> str:
    d = datetime.fromisoformat(date).date()
    return (d - timedelta(days=1)).isoformat()


async def run_daily_aggregation(store: Store, date: str,
                                alpha_min: float, beta_min: float,
                                stage_a_top_n: int, stage_b_top_n: int) -> list[Candidate]:
    today_counts = await store.daily_mention_counts(date)
    if not today_counts:
        return []

    # Stage A：按 mention 取 top N
    sorted_today = sorted(today_counts.items(), key=lambda kv: kv[1], reverse=True)
    candidates = sorted_today[:stage_a_top_n]

    # Stage B：加权分（v1 interactions=0，回退为 mention）
    today_weighted = {sym: weighted_score(cnt, 0) for sym, cnt in candidates}
    market_avg = sum(today_weighted.values()) / max(1, len(today_weighted))

    yesterday = _prev_day(date)
    yesterday_counts = await store.daily_mention_counts(yesterday)
    yesterday_weighted = {sym: weighted_score(cnt, 0) for sym, cnt in yesterday_counts.items()}

    cands: list[Candidate] = []
    for sym, w_today in today_weighted.items():
        w_yest = yesterday_weighted.get(sym, 0.0)
        a, b = compute_alpha_beta(w_today, w_yest, market_avg)
        cands.append(Candidate(symbol=sym, alpha=a, beta=b, composite=0.0,
                               mention=today_counts[sym], weighted=w_today))

    top = select_top(cands, alpha_min=alpha_min, beta_min=beta_min, top_n=stage_b_top_n)

    for c in cands:
        await store.upsert_daily_score(
            symbol=c.symbol, date=date, mention_count=c.mention,
            weighted_score=c.weighted,
            alpha=(None if c.alpha == math.inf else c.alpha),
            beta=c.beta, composite=c.composite,
        )
    return top

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

    # market_avg 必须基于全市场（而非仅 Stage A 候选），否则平均值被热门标的抬高、β 普遍偏低。
    today_weighted_all = {sym: weighted_score(cnt, 0) for sym, cnt in today_counts.items()}
    market_avg = sum(today_weighted_all.values()) / max(1, len(today_weighted_all))

    # Stage A：按 mention 取 top N 进入候选池
    sorted_today = sorted(today_counts.items(), key=lambda kv: kv[1], reverse=True)
    candidates = sorted_today[:stage_a_top_n]
    today_weighted = {sym: today_weighted_all[sym] for sym, _ in candidates}

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
    qualified_syms = {c.symbol for c in top}

    for c in cands:
        # 仅入选者持久化 composite；未达标者写 NULL，避免 0 被误读为"已计算且为零"。
        composite_val = c.composite if c.symbol in qualified_syms else None
        await store.upsert_daily_score(
            symbol=c.symbol, date=date, mention_count=c.mention,
            weighted_score=c.weighted,
            alpha=(None if c.alpha == math.inf else c.alpha),
            beta=c.beta, composite=composite_val,
        )
    return top

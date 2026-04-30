import math
from dataclasses import dataclass


@dataclass
class Candidate:
    symbol: str
    alpha: float
    beta: float
    composite: float
    mention: int
    weighted: float


def compute_alpha_beta(today: float, yesterday: float, market_avg: float) -> tuple[float, float]:
    alpha = math.inf if yesterday <= 0 else (today / yesterday - 1.0)
    beta = 0.0 if market_avg <= 0 else today / market_avg
    return alpha, beta


def compose(alpha: float, beta: float) -> float:
    if alpha == math.inf:
        # 冷启动：仅按 beta 排序
        return math.log10(1.0 + max(0.0, beta))
    return alpha * math.log10(1.0 + max(0.0, beta))


def select_top(cands: list[Candidate], alpha_min: float, beta_min: float, top_n: int) -> list[Candidate]:
    qualified = [c for c in cands if c.alpha >= alpha_min and c.beta >= beta_min]
    for c in qualified:
        c.composite = compose(c.alpha, c.beta)
    qualified.sort(key=lambda x: x.composite, reverse=True)
    return qualified[:top_n]

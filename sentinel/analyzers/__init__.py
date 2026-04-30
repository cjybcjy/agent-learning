from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sentinel.collectors.base import RawMention
from sentinel.domain.models import HeatSnapshot, Market


@dataclass(slots=True)
class WeightsConfig:
    posts: float = 0.35
    comments: float = 0.30
    likes: float = 0.20
    shares: float = 0.15
    kol_multiplier: float = 3.0


def compute_heat(
    mentions: list[RawMention],
    weights: WeightsConfig,
    timestamp: datetime,
    sentiment_score: float = 0.0,
) -> list[HeatSnapshot]:
    """Aggregate mentions per symbol and compute directed heat scores.

    sentiment_score is a placeholder (0.0 = neutral) until FinBERT is integrated.
    """
    if not mentions:
        return []

    # Aggregate per symbol
    symbol_agg: dict[str, _SymbolAgg] = {}
    for m in mentions:
        agg = symbol_agg.setdefault(m.symbol, _SymbolAgg(market=m.market, symbol=m.symbol))
        agg.post_count += m.post_count
        agg.comment_count += m.comment_count
        agg.like_count += m.like_count
        agg.share_count += m.share_count
        agg.total_mentions += 1
        if m.is_kol:
            agg.kol_mentions += 1
        # Track top source platform
        agg.platform_counts[m.platform] = agg.platform_counts.get(m.platform, 0) + 1

    # Min-max normalization across all symbols in this batch
    all_aggs = list(symbol_agg.values())
    max_posts = max((a.post_count for a in all_aggs), default=1) or 1
    max_comments = max((a.comment_count for a in all_aggs), default=1) or 1
    max_likes = max((a.like_count for a in all_aggs), default=1) or 1
    max_shares = max((a.share_count for a in all_aggs), default=1) or 1

    snapshots: list[HeatSnapshot] = []
    for agg in all_aggs:
        p_norm = agg.post_count / max_posts
        c_norm = agg.comment_count / max_comments
        l_norm = agg.like_count / max_likes
        s_norm = agg.share_count / max_shares

        v_base = (
            weights.posts * p_norm
            + weights.comments * c_norm
            + weights.likes * l_norm
            + weights.shares * s_norm
        )

        kol_ratio = agg.kol_mentions / agg.total_mentions if agg.total_mentions else 0
        m_kol = 1.0 + weights.kol_multiplier * kol_ratio

        directed_heat = v_base * m_kol * sentiment_score if sentiment_score != 0.0 else v_base * m_kol

        top_source = max(agg.platform_counts, key=agg.platform_counts.get)  # type: ignore[arg-type]

        snapshots.append(
            HeatSnapshot(
                timestamp=timestamp,
                market=agg.market,
                symbol=agg.symbol,
                base_heat=round(v_base, 4),
                kol_multiplier=round(m_kol, 4),
                sentiment_score=sentiment_score,
                directed_heat=round(directed_heat, 4),
                change_pct=None,
                top_source=top_source,
                rank_bullish=None,
                rank_bearish=None,
                is_anomaly=False,
            )
        )

    return snapshots


@dataclass
class _SymbolAgg:
    market: Market
    symbol: str
    post_count: int = 0
    comment_count: int = 0
    like_count: int = 0
    share_count: int = 0
    total_mentions: int = 0
    kol_mentions: int = 0
    platform_counts: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.platform_counts is None:
            self.platform_counts = {}

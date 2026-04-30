import math

from heatmap.aggregator.gates import Candidate, compose, compute_alpha_beta, select_top


def test_alpha_normal():
    a, b = compute_alpha_beta(today=150, yesterday=100, market_avg=50)
    assert a == 0.5
    assert b == 3.0


def test_alpha_cold_start_yesterday_zero():
    a, _ = compute_alpha_beta(today=10, yesterday=0, market_avg=5)
    assert a == math.inf


def test_compose_uses_log10_of_beta():
    assert compose(alpha=1.0, beta=9.0) == 1.0 * math.log10(10.0)


def test_select_top_filters_by_thresholds_and_limits():
    cands = [
        Candidate("A", alpha=0.6, beta=2.0, composite=0.0, mention=10, weighted=10),
        Candidate("B", alpha=0.4, beta=3.0, composite=0.0, mention=10, weighted=10),
        Candidate("C", alpha=1.0, beta=1.2, composite=0.0, mention=10, weighted=10),
        Candidate("D", alpha=2.0, beta=5.0, composite=0.0, mention=10, weighted=10),
    ]
    top = select_top(cands, alpha_min=0.5, beta_min=1.5, top_n=10)
    assert [c.symbol for c in top] == ["D", "A"]


def test_select_top_places_new_above_regular():
    """冷启动 NEW (alpha=inf) 必须置顶，且按 beta 内部排序，不与常规项混排。"""
    cands = [
        Candidate("REG_HI", alpha=10.0, beta=10.0, composite=0.0, mention=10, weighted=10),
        Candidate("NEW_LO", alpha=math.inf, beta=2.0, composite=0.0, mention=10, weighted=10),
        Candidate("NEW_HI", alpha=math.inf, beta=8.0, composite=0.0, mention=10, weighted=10),
        Candidate("REG_LO", alpha=0.6, beta=2.0, composite=0.0, mention=10, weighted=10),
    ]
    top = select_top(cands, alpha_min=0.5, beta_min=1.5, top_n=10)
    assert [c.symbol for c in top] == ["NEW_HI", "NEW_LO", "REG_HI", "REG_LO"]

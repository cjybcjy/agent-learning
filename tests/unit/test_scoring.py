import math
import pytest
from heatmap.aggregator.scoring import weighted_score


def test_weighted_score_zero_interactions_falls_back_to_mention():
    assert weighted_score(mention=10, interactions=0) == pytest.approx(10.0)


def test_weighted_score_uses_log10():
    # interactions=99 → 1 + log10(100) = 3
    assert weighted_score(mention=2, interactions=99) == pytest.approx(2 * 3.0)


def test_weighted_score_never_zero_when_mention_positive():
    assert weighted_score(mention=1, interactions=0) > 0

from __future__ import annotations

import math

import pytest

from sentinel.mgfs.percentile_engine import PercentileEngine


def test_percentile_basic():
    engine = PercentileEngine()
    history = [10] * 100 + [20] * 100 + [30] * 100
    result = engine.compute_percentile(history)
    assert math.isclose(result, 200 / 299 * 100, rel_tol=1e-9)


def test_percentile_at_maximum():
    engine = PercentileEngine()
    history = list(range(1, 101))
    result = engine.compute_percentile(history)
    assert result == 100.0


def test_percentile_at_minimum():
    engine = PercentileEngine()
    history = list(range(100, 0, -1))
    result = engine.compute_percentile(history)
    assert result == 0.0


def test_percentile_insufficient_data():
    engine = PercentileEngine()
    history = [1, 2, 3]
    result = engine.compute_percentile(history)
    assert result == 50.0


def test_percentile_negative_current_returns_sentinel():
    engine = PercentileEngine()
    history = [10] * 100 + [-5]
    result = engine.compute_percentile(history)
    assert result == -1.0


def test_percentile_negative_history_excluded():
    engine = PercentileEngine()
    history = [-1] * 50 + list(range(1, 51)) + [30]
    result = engine.compute_percentile(history)
    assert result == (29 / 50) * 100


def test_percentile_all_negative_history_falls_back():
    engine = PercentileEngine()
    history = [-1, -2, -3, -4]
    result = engine.compute_percentile(history)
    assert result == 50.0

from __future__ import annotations

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.data.valuation_fetcher import MockValuationFetcher


def test_mock_fetcher_returns_expected_sequence():
    fetcher = MockValuationFetcher(seed=42)
    result = fetcher.fetch_history("000001.SZ", Market.A_SHARE, "PE", years=5)

    assert len(result) == 5 * 250
    assert all(v > 0 for v in result)

    fetcher2 = MockValuationFetcher(seed=42)
    result2 = fetcher2.fetch_history("000001.SZ", Market.A_SHARE, "PE", years=5)
    assert result == result2


def test_mock_fetcher_different_seeds_produce_different_results():
    fetcher1 = MockValuationFetcher(seed=1)
    fetcher2 = MockValuationFetcher(seed=2)

    result1 = fetcher1.fetch_history("000001.SZ", Market.A_SHARE, "PE", years=5)
    result2 = fetcher2.fetch_history("000001.SZ", Market.A_SHARE, "PE", years=5)

    assert result1 != result2


def test_mock_fetcher_returns_list_of_floats():
    fetcher = MockValuationFetcher(seed=42)
    result = fetcher.fetch_history("000001.SZ", Market.A_SHARE, "PE", years=5)

    assert isinstance(result, list)
    assert all(isinstance(v, float) for v in result)

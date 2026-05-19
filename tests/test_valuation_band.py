from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.data.valuation_fetcher import MockValuationFetcher
from sentinel.web.services.valuation_chart_service import (
    build_valuation_band_data,
    compute_percentiles,
)


class TestComputePercentiles:
    def test_percentiles_basic(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        p10, p50, p90 = compute_percentiles(values)
        assert p10 == pytest.approx(19.0, abs=1.0)
        assert p50 == pytest.approx(55.0, abs=1.0)
        assert p90 == pytest.approx(91.0, abs=1.0)

    def test_percentiles_empty(self) -> None:
        assert compute_percentiles([]) == (0.0, 0.0, 0.0)

    def test_percentiles_single_value(self) -> None:
        assert compute_percentiles([50.0]) == (50.0, 50.0, 50.0)


class TestBuildValuationBandData:
    def test_build_band_with_mock_fetcher(self) -> None:
        fetcher = MockValuationFetcher(seed=42)
        data = build_valuation_band_data(
            symbol="600519",
            market=Market.A_SHARE,
            sector="白酒",
            fetcher=fetcher,
        )
        assert data is not None
        assert data["metric_name"] == "PE_TTM"  # 白酒默认传统成长
        assert "dates" in data
        assert "values" in data
        assert "p10" in data
        assert "p50" in data
        assert "p90" in data
        assert len(data["dates"]) == len(data["values"])

    def test_build_band_for_bank_sector(self) -> None:
        fetcher = MockValuationFetcher(seed=42)
        data = build_valuation_band_data(
            symbol="000001",
            market=Market.A_SHARE,
            sector="银行",
            fetcher=fetcher,
        )
        # 银行 sector 映射到 heavy_asset_cyclical -> PB
        assert data is not None
        assert data["metric_name"] == "PB"

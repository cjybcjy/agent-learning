from __future__ import annotations

import pytest

from sentinel.mgfs.execution.position_sizing import PositionSizingEngine


class TestPositionSizingEngine:
    """TDD for MGFS 1.5 PositionSizingEngine — 出海制造五虎将过载测试."""

    @pytest.fixture
    def engine(self) -> PositionSizingEngine:
        # 白酒 raw allocation ~43%, sector limit 25% 强制压缩; 验证压缩后不归一化膨胀
        sector_limits = {
            "白酒": 0.25,
            "新能源": 0.30,
            "家电": 0.25,
        }
        return PositionSizingEngine(
            sector_limits=sector_limits,
            kelly_k=0.15,
            kelly_x0=78.0,
            kelly_half_factor=0.5,
            min_kelly_fraction=0.0,
            max_kelly_fraction=0.25,
        )

    def test_five_tigers_baijiu_overloaded_then_clipped_and_normalized(self, engine):
        """
        五虎将候选集，白酒 sector 满载 45%。
        验证：
        1. 白酒 sector 被压缩到 25% 上限
        2. 总仓位不超过 100%
        3. 压缩后剩余部分变现金储备，不归一化重新膨胀
        """
        candidates = [
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "sector": "白酒",
                "final_score": 92.5,
                "payoff_ratio": 2.5,
            },
            {
                "symbol": "000858",
                "name": "五粮液",
                "sector": "白酒",
                "final_score": 88.0,
                "payoff_ratio": 2.3,
            },
            {
                "symbol": "300750",
                "name": "宁德时代",
                "sector": "新能源",
                "final_score": 88.0,
                "payoff_ratio": 2.0,
            },
            {
                "symbol": "300760",
                "name": "迈瑞医疗",
                "sector": "医疗",
                "final_score": 85.0,
                "payoff_ratio": 1.8,
            },
            {
                "symbol": "000333",
                "name": "美的集团",
                "sector": "家电",
                "final_score": 82.0,
                "payoff_ratio": 1.5,
            },
            {
                "symbol": "600690",
                "name": "海尔智家",
                "sector": "家电",
                "final_score": 80.0,
                "payoff_ratio": 1.5,
            },
        ]

        portfolio = engine.build_portfolio(candidates)

        # 1. 总仓位 <= 100%
        total_weight = sum(h["weight"] for h in portfolio["holdings"])
        assert total_weight <= 1.0 + 1e-9, f"total weight {total_weight} exceeds 1.0"

        # 2. 白酒 sector 被压缩到 25% 以内
        baijiu_weight = sum(
            h["weight"] for h in portfolio["holdings"] if h["sector"] == "白酒"
        )
        assert baijiu_weight <= 0.25 + 1e-9, f"baijiu weight {baijiu_weight} exceeds 0.25"

        # 3. 家电 sector 不超过 25%
        jiadian_weight = sum(
            h["weight"] for h in portfolio["holdings"] if h["sector"] == "家电"
        )
        assert jiadian_weight <= 0.25 + 1e-9, f"jiadian weight {jiadian_weight} exceeds 0.25"

        # 4. 现金储备 >= 0（因为压缩后总仓位可能 < 100%，剩余变现金）
        assert portfolio["cash_reserve"] >= -1e-9
        assert portfolio["cash_reserve"] == pytest.approx(1.0 - total_weight, abs=1e-9)

        # 5. 每个持仓 weight > 0 且 <= max_kelly_fraction (0.25)
        for h in portfolio["holdings"]:
            assert 0.0 < h["weight"] <= 0.25 + 1e-9
            assert "kelly_fraction" in h
            assert "stop_loss_hard" in h
            assert "stop_loss_trailing" in h

    def test_negative_ev_returns_zero_weight(self, engine):
        """负期望价值应返回 0 仓位，不进入组合."""
        candidates = [
            {
                "symbol": "000001",
                "name": "负期望标的",
                "sector": "测试",
                "final_score": 30.0,  # 低分 → 低胜率
                "payoff_ratio": 0.3,  # 低赔率 → 负 EV
            },
        ]
        portfolio = engine.build_portfolio(candidates)
        assert len(portfolio["holdings"]) == 0
        assert portfolio["cash_reserve"] == pytest.approx(1.0, abs=1e-9)

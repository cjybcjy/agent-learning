from __future__ import annotations

from pathlib import Path
from typing import Any

from sentinel.mgfs.archetype_router import ArchetypeRouter
from sentinel.mgfs.data.price_fetcher import MockPriceFetcher, OHLCV, PriceFetcher
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo


class TimingFactorPlugin(BaseFactorPlugin):
    """Module C — Quantitative timing & momentum factor.

    Evaluates the *technical entry quality* of a stock by measuring:
    1. Bias relative to 60-day moving average (ideal entry zone)
    2. Trend slope of the 60-day MA ("catching a falling knife" guard)
    3. ATR-based dynamic band expansion (adaptive to volatility regime)
    """

    factor_key = "timing"
    factor_name = "量化择时"
    default_weight = 0.1

    # Static defaults (overridden by archetype.timing in YAML)
    DEFAULT_IDEAL_BAND = 0.02
    DEFAULT_ACCEPTABLE_BAND = 0.05
    DEFAULT_VETO_THRESHOLD = -0.03
    DEFAULT_MAX_BONUS = 10.0
    DEFAULT_MAX_PENALTY = -40.0
    DEFAULT_BULLISH_REF = 0.02
    DEFAULT_ATR_BASELINE = 0.015
    DEFAULT_ATR_K = 1.0
    DEFAULT_ATR_MIN_MULT = 0.5
    DEFAULT_ATR_MAX_MULT = 2.0

    def __init__(
        self,
        config_path: Path | None = None,
        fetcher: PriceFetcher | None = None,
    ) -> None:
        self._router = ArchetypeRouter(config_path)
        self._fetcher = fetcher if fetcher is not None else MockPriceFetcher()

    def evaluate(self, target: TargetInfo) -> FactorScore:
        # 1. Fetch price history
        ohlcv = self._fetcher.fetch_ohlcv(target.symbol, target.market, days=120)
        if len(ohlcv) < 80:
            return FactorScore(
                factor_key=self.factor_key,
                factor_name=self.factor_name,
                score=50.0,
                weight=self.default_weight,
                confidence=0.3,
                warnings=[f"K线数据不足 ({len(ohlcv)} 根)，无法计算 60 日均线"],
            )

        closes = [bar.close for bar in ohlcv]

        # 2. Compute MA60 and bias
        ma60 = sum(closes[-60:]) / 60
        latest_close = closes[-1]
        bias = (latest_close - ma60) / ma60 if ma60 > 0 else 0.0

        # 3. Compute 60-day MA trend slope (20-day delta)
        ma60_20d_ago = sum(closes[-80:-20]) / 60
        trend_slope = (
            (ma60 - ma60_20d_ago) / ma60_20d_ago if ma60_20d_ago > 0 else 0.0
        )

        # 4. Compute ATR(14) and volatility coefficient
        atr = self._compute_atr(ohlcv, period=14)
        atr_ratio = atr / latest_close if latest_close > 0 else 0.0

        # 5. Resolve archetype for timing parameters
        archetype = self._router.resolve_archetype(target.symbol, target.sector)
        timing_cfg = archetype.get("timing", {}) if archetype else {}

        # 6. Score
        score, warnings = self._score_bias(
            bias=bias,
            trend_slope=trend_slope,
            atr_ratio=atr_ratio,
            timing_cfg=timing_cfg,
        )

        # 7. Confidence
        data_quality = len(ohlcv)
        if data_quality >= 500:
            confidence = 0.85
        elif data_quality >= 250:
            confidence = 0.75
        else:
            confidence = 0.65

        details: dict[str, Any] = {
            "ma60": round(ma60, 2),
            "bias": round(bias, 4),
            "trend_slope": round(trend_slope, 4),
            "atr14": round(atr, 2),
            "atr_ratio": round(atr_ratio, 4),
            "archetype": archetype.get("label") if archetype else None,
        }

        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=round(score, 2),
            weight=self.default_weight,
            details=details,
            confidence=round(confidence, 2),
            warnings=warnings,
        )

    @staticmethod
    def _compute_atr(ohlcv: list[OHLCV], period: int = 14) -> float:
        """Compute Average True Range over the given period."""
        trs: list[float] = []
        for i in range(1, len(ohlcv)):
            high = ohlcv[i].high
            low = ohlcv[i].low
            prev_close = ohlcv[i - 1].close
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            trs.append(tr)
        if not trs:
            return 0.0
        if len(trs) < period:
            return sum(trs) / len(trs)
        return sum(trs[-period:]) / period

    def _score_bias(
        self,
        bias: float,
        trend_slope: float,
        atr_ratio: float,
        timing_cfg: dict[str, Any],
    ) -> tuple[float, list[str]]:
        """Core scoring logic for timing factor.

        Args:
            bias: (price - ma60) / ma60.
            trend_slope: 20-day slope of 60-day MA.
            atr_ratio: ATR(14) / latest close.
            timing_cfg: Archetype-specific timing parameters.

        Returns:
            (score, warnings)
        """
        warnings: list[str] = []

        # --- Parameters (with archetype override support) ---
        static_ideal = timing_cfg.get("ideal_band", self.DEFAULT_IDEAL_BAND)
        static_acceptable = timing_cfg.get(
            "acceptable_band", self.DEFAULT_ACCEPTABLE_BAND
        )
        veto_threshold = timing_cfg.get(
            "slope_veto_threshold", self.DEFAULT_VETO_THRESHOLD
        )
        max_bonus = timing_cfg.get("max_bonus", self.DEFAULT_MAX_BONUS)
        max_penalty = timing_cfg.get("max_penalty", self.DEFAULT_MAX_PENALTY)
        bullish_ref = timing_cfg.get("bullish_ref", self.DEFAULT_BULLISH_REF)
        atr_baseline = timing_cfg.get("atr_baseline", self.DEFAULT_ATR_BASELINE)
        atr_k = timing_cfg.get("atr_k", self.DEFAULT_ATR_K)
        atr_min_mult = timing_cfg.get("atr_min_mult", self.DEFAULT_ATR_MIN_MULT)
        atr_max_mult = timing_cfg.get("atr_max_mult", self.DEFAULT_ATR_MAX_MULT)

        # --- ATR-based dynamic band expansion ---
        # 波动率系数: ATR高时击球带撑大, ATR低时收紧
        volatility_factor = 1.0 + (atr_ratio - atr_baseline) / atr_baseline * atr_k
        volatility_factor = max(atr_min_mult, min(atr_max_mult, volatility_factor))

        ideal_band = static_ideal * volatility_factor
        acceptable_band = static_acceptable * volatility_factor

        # --- 1. Bias base score ---
        abs_bias = abs(bias)
        if abs_bias <= ideal_band:
            base_score = 100.0
        elif abs_bias <= acceptable_band:
            # Linear decay: 100 -> 70 across the extended band
            base_score = 100.0 - (
                (abs_bias - ideal_band)
                / (acceptable_band - ideal_band)
                * 30.0
            )
        else:
            # Accelerated decay beyond acceptable band
            excess = abs_bias - acceptable_band
            band_width = acceptable_band  # Use band as decay reference unit
            decay = (excess / band_width) * 70.0 if band_width > 0 else 70.0
            base_score = max(70.0 - decay, 0.0)

        # --- 2. Trend slope veto ("catching a falling knife") ---
        if trend_slope < veto_threshold:
            warnings.append(
                f"60日均线斜率 {trend_slope:.2%}（阈值 {veto_threshold:.2%}），"
                f"触发择时一票否决"
            )
            return 0.0, warnings

        # --- 3. Trend slope modulation ---
        if trend_slope >= 0:
            # Upward trend: bonus capped at max_bonus
            bonus = min(trend_slope / bullish_ref * max_bonus, max_bonus)
        else:
            # Downward but above veto: non-linear penalty
            # normalized: 0 at flat, 1 at veto boundary
            normalized = trend_slope / veto_threshold  # Both negative -> positive ratio
            # Squared penalty: gentle near flat, severe near veto
            penalty = -(normalized**2) * abs(max_penalty)
            bonus = penalty

        score = base_score + bonus
        return max(0.0, min(100.0, score)), warnings

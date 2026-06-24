from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sentinel.mgfs.data.price_fetcher import OHLCV


@dataclass(frozen=True, slots=True)
class TechnicalSnapshot:
    date: str
    close: float
    ma20: float | None
    ma60: float | None
    ma120: float | None
    rsi14: float | None
    atr14: float | None
    volume_ratio20: float | None
    bias60: float | None
    ma60_slope20: float | None
    entry_watch: bool = False
    entry_label: str = "none"
    entry_tags: list[str] = field(default_factory=list)
    exit_watch: bool = False
    exit_label: str = "none"
    exit_tags: list[str] = field(default_factory=list)
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    stop_reference: float | None = None
    instruction_boundary: str = "research_only"

    def to_details(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "close": round(self.close, 2),
            "ma20": _round_optional(self.ma20),
            "ma60": _round_optional(self.ma60),
            "ma120": _round_optional(self.ma120),
            "rsi14": _round_optional(self.rsi14),
            "atr14": _round_optional(self.atr14),
            "volume_ratio20": _round_optional(self.volume_ratio20),
            "bias60": _round_optional(self.bias60, digits=4),
            "ma60_slope20": _round_optional(self.ma60_slope20, digits=4),
            "entry_watch": self.entry_watch,
            "entry_label": self.entry_label,
            "entry_tags": list(self.entry_tags),
            "exit_watch": self.exit_watch,
            "exit_label": self.exit_label,
            "exit_tags": list(self.exit_tags),
            "entry_zone_low": _round_optional(self.entry_zone_low),
            "entry_zone_high": _round_optional(self.entry_zone_high),
            "stop_reference": _round_optional(self.stop_reference),
            "instruction_boundary": self.instruction_boundary,
        }


@dataclass(frozen=True, slots=True)
class TechnicalSignalReport:
    snapshots: list[TechnicalSnapshot]

    @property
    def latest(self) -> TechnicalSnapshot:
        if not self.snapshots:
            raise ValueError("TechnicalSignalReport has no snapshots")
        return self.snapshots[-1]


class AShareTechnicalStrategy:
    """Freqtrade-style indicator -> entry -> exit pipeline for A-share research."""

    ENTRY_MIN_VOLUME_RATIO = 1.2
    EXIT_MIN_VOLUME_RATIO = 1.3
    ENTRY_BIAS_LOW = -0.035
    ENTRY_BIAS_HIGH = 0.035
    EXIT_BIAS = -0.06

    def analyze(self, bars: list[OHLCV]) -> TechnicalSignalReport:
        return self.analyze_as_of(bars, as_of_index=len(bars) - 1)

    def analyze_as_of(
        self,
        bars: list[OHLCV],
        *,
        as_of_index: int,
    ) -> TechnicalSignalReport:
        if not bars:
            raise ValueError("at least one OHLCV bar is required")
        if as_of_index < 0 or as_of_index >= len(bars):
            raise IndexError("as_of_index must point to an existing bar")

        rows = self.populate_indicators(bars[: as_of_index + 1])
        rows = self.populate_entry_trend(rows)
        rows = self.populate_exit_trend(rows)
        return TechnicalSignalReport(
            snapshots=[self._snapshot_from_row(row) for row in rows]
        )

    def populate_indicators(self, bars: list[OHLCV]) -> list[dict[str, Any]]:
        closes = [bar.close for bar in bars]
        rows: list[dict[str, Any]] = []
        for idx, bar in enumerate(bars):
            ma20 = self._sma(closes, idx, 20)
            ma60 = self._sma(closes, idx, 60)
            ma120 = self._sma(closes, idx, 120)
            rsi14 = self._rsi(closes, idx, 14)
            atr14 = self._atr(bars, idx, 14)
            volume_ratio20 = self._volume_ratio(bars, idx, 20)
            ma60_slope20 = self._ma_slope(closes, idx, period=60, lookback=20)
            bias60 = (
                (bar.close - ma60) / ma60
                if ma60 is not None and ma60 > 0
                else None
            )
            entry_zone_low, entry_zone_high, stop_reference = (
                self._research_zones(bar.close, ma60, atr14)
            )
            rows.append(
                {
                    "date": bar.date,
                    "open": bar.open,
                    "close": bar.close,
                    "ma20": ma20,
                    "ma60": ma60,
                    "ma120": ma120,
                    "rsi14": rsi14,
                    "atr14": atr14,
                    "volume_ratio20": volume_ratio20,
                    "bias60": bias60,
                    "ma60_slope20": ma60_slope20,
                    "entry_zone_low": entry_zone_low,
                    "entry_zone_high": entry_zone_high,
                    "stop_reference": stop_reference,
                    "entry_watch": False,
                    "entry_label": "none",
                    "entry_tags": [],
                    "exit_watch": False,
                    "exit_label": "none",
                    "exit_tags": [],
                }
            )
        return rows

    def populate_entry_trend(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        for row in rows:
            tags: list[str] = []
            if self._is_pullback_recovery(row):
                tags.append("pullback_recovery")
            if self._is_ma_stack_constructive(row):
                tags.append("ma_stack_constructive")

            row["entry_tags"] = tags
            row["entry_watch"] = bool(tags)
            row["entry_label"] = "entry_watch" if tags else "none"
        return rows

    def populate_exit_trend(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        for row in rows:
            tags: list[str] = []
            if self._is_volume_breakdown(row):
                tags.append("volume_breakdown")
            if self._is_trend_breakdown(row):
                tags.append("trend_breakdown")

            row["exit_tags"] = tags
            row["exit_watch"] = bool(tags)
            row["exit_label"] = "exit_risk" if tags else "none"
            if tags:
                row["entry_watch"] = False
                row["entry_label"] = "none"
                row["entry_tags"] = []
        return rows

    @staticmethod
    def _sma(closes: list[float], idx: int, period: int) -> float | None:
        if idx + 1 < period:
            return None
        window = closes[idx + 1 - period : idx + 1]
        return sum(window) / period

    @staticmethod
    def _ma_slope(
        closes: list[float],
        idx: int,
        *,
        period: int,
        lookback: int,
    ) -> float | None:
        current = AShareTechnicalStrategy._sma(closes, idx, period)
        prior = AShareTechnicalStrategy._sma(closes, idx - lookback, period)
        if current is None or prior is None or prior <= 0:
            return None
        return (current - prior) / prior

    @staticmethod
    def _rsi(closes: list[float], idx: int, period: int) -> float | None:
        if idx < period:
            return None
        gains = 0.0
        losses = 0.0
        for i in range(idx - period + 1, idx + 1):
            change = closes[i] - closes[i - 1]
            if change >= 0:
                gains += change
            else:
                losses += abs(change)
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def _atr(bars: list[OHLCV], idx: int, period: int) -> float | None:
        if idx == 0:
            return None
        start = max(1, idx - period + 1)
        true_ranges: list[float] = []
        for i in range(start, idx + 1):
            bar = bars[i]
            prev_close = bars[i - 1].close
            true_ranges.append(
                max(
                    bar.high - bar.low,
                    abs(bar.high - prev_close),
                    abs(bar.low - prev_close),
                )
            )
        return sum(true_ranges) / len(true_ranges) if true_ranges else None

    @staticmethod
    def _volume_ratio(
        bars: list[OHLCV],
        idx: int,
        period: int,
    ) -> float | None:
        if idx < period:
            return None
        window = bars[idx - period : idx]
        avg_volume = sum(bar.volume for bar in window) / period
        if avg_volume <= 0:
            return None
        return bars[idx].volume / avg_volume

    @staticmethod
    def _research_zones(
        close: float,
        ma60: float | None,
        atr14: float | None,
    ) -> tuple[float | None, float | None, float | None]:
        if ma60 is None or atr14 is None or close <= 0:
            return None, None, None
        atr_ratio = atr14 / close
        dynamic_band = max(0.025, min(0.08, atr_ratio * 1.8))
        entry_zone_low = ma60 * (1.0 - dynamic_band)
        entry_zone_high = ma60 * (1.0 + dynamic_band * 0.5)
        stop_reference = ma60 - atr14 * 2.0
        return entry_zone_low, entry_zone_high, stop_reference

    def _is_pullback_recovery(self, row: dict[str, Any]) -> bool:
        bias = row["bias60"]
        slope = row["ma60_slope20"]
        volume_ratio = row["volume_ratio20"]
        rsi = row["rsi14"]
        if bias is None or slope is None or volume_ratio is None:
            return False
        if not (self.ENTRY_BIAS_LOW <= bias <= self.ENTRY_BIAS_HIGH):
            return False
        if slope <= 0:
            return False
        if row["close"] <= row["open"]:
            return False
        if volume_ratio < self.ENTRY_MIN_VOLUME_RATIO:
            return False
        return rsi is None or 35.0 <= rsi <= 72.0

    @staticmethod
    def _is_ma_stack_constructive(row: dict[str, Any]) -> bool:
        ma20 = row["ma20"]
        ma60 = row["ma60"]
        ma120 = row["ma120"]
        slope = row["ma60_slope20"]
        close = row["close"]
        if ma20 is None or ma60 is None or ma120 is None or slope is None:
            return False
        return ma20 >= ma60 >= ma120 and close >= ma60 and slope > 0

    def _is_volume_breakdown(self, row: dict[str, Any]) -> bool:
        bias = row["bias60"]
        volume_ratio = row["volume_ratio20"]
        if bias is None or volume_ratio is None:
            return False
        return (
            bias <= self.EXIT_BIAS
            and volume_ratio >= self.EXIT_MIN_VOLUME_RATIO
            and row["close"] < row["open"]
        )

    @staticmethod
    def _is_trend_breakdown(row: dict[str, Any]) -> bool:
        ma20 = row["ma20"]
        ma60 = row["ma60"]
        bias = row["bias60"]
        close = row["close"]
        if ma20 is None or ma60 is None or bias is None:
            return False
        return close < ma60 and ma20 < ma60 and bias <= -0.03

    @staticmethod
    def _snapshot_from_row(row: dict[str, Any]) -> TechnicalSnapshot:
        return TechnicalSnapshot(
            date=row["date"],
            close=row["close"],
            ma20=row["ma20"],
            ma60=row["ma60"],
            ma120=row["ma120"],
            rsi14=row["rsi14"],
            atr14=row["atr14"],
            volume_ratio20=row["volume_ratio20"],
            bias60=row["bias60"],
            ma60_slope20=row["ma60_slope20"],
            entry_watch=row["entry_watch"],
            entry_label=row["entry_label"],
            entry_tags=list(row["entry_tags"]),
            exit_watch=row["exit_watch"],
            exit_label=row["exit_label"],
            exit_tags=list(row["exit_tags"]),
            entry_zone_low=row["entry_zone_low"],
            entry_zone_high=row["entry_zone_high"],
            stop_reference=row["stop_reference"],
        )


def _round_optional(value: float | None, *, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None

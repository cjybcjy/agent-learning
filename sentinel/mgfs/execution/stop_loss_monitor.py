from __future__ import annotations

import logging
from dataclasses import dataclass

from sentinel.mgfs.storage.mgfs_repository import MGFSRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RiskAlert:
    alert_type: str
    symbol: str
    name: str
    current_price: float
    trigger_price: float
    suggested_action: str


class StopLossMonitor:
    """Scan active holdings and emit risk alerts for three-level stop-loss triggers."""

    ALERT_HARD = "HARD_STOP"
    ALERT_TRAILING = "TRAILING_STOP"
    ALERT_PORTFOLIO = "PORTFOLIO_EMERGENCY"

    ACTION_MARKET_SELL = "MARKET_SELL"
    ACTION_REVIEW_IMMEDIATELY = "REVIEW_IMMEDIATELY"

    def __init__(self, repository: MGFSRepository) -> None:
        self.repository = repository

    def scan(self) -> list[RiskAlert]:
        """Return all active risk alerts across holdings.

        Guards against zero/negative prices to prevent false alerts from
        suspended stocks or dirty data.
        """
        holdings = self.repository.list_active_holdings()
        alerts: list[RiskAlert] = []
        valid_holdings: list[dict] = []

        for h in holdings:
            if not self._is_price_valid(h.get("current_price")):
                logger.warning(
                    "StopLossMonitor: invalid current_price for %s (%s), skipping",
                    h.get("symbol"), h.get("name"),
                )
                continue
            if not self._is_price_valid(h.get("entry_price")):
                logger.warning(
                    "StopLossMonitor: invalid entry_price for %s (%s), skipping",
                    h.get("symbol"), h.get("name"),
                )
                continue
            if not self._is_price_valid(h.get("highest_price")):
                logger.warning(
                    "StopLossMonitor: invalid highest_price for %s (%s), skipping",
                    h.get("symbol"), h.get("name"),
                )
                continue
            valid_holdings.append(h)

        for h in valid_holdings:
            alerts.extend(self._check_individual_stops(h))

        alerts.extend(self._check_portfolio_emergency(valid_holdings))
        return alerts

    # -- dismiss handlers ---------------------------------------------------

    def dismiss_and_close_position(self, symbol: str) -> None:
        """Path A: close the position so it will not re-trigger tomorrow."""
        self.repository.delete_active_holding(symbol)
        logger.info("StopLossMonitor: position %s closed (dismiss path A)", symbol)

    def dismiss_and_reset_baseline(self, symbol: str, new_price: float) -> None:
        """Path B: reset entry_price and highest_price to new_price.

        This establishes a new defense baseline so the same alert
        does not zombie-resurrect on the next scan.
        """
        if not self._is_price_valid(new_price):
            logger.warning(
                "StopLossMonitor: cannot reset baseline for %s with invalid price %s",
                symbol, new_price,
            )
            return
        self.repository.reset_holding_baseline(symbol, new_price)
        logger.info(
            "StopLossMonitor: baseline for %s reset to %.2f (dismiss path B)",
            symbol, new_price,
        )

    # -- internal -----------------------------------------------------------

    @staticmethod
    def _is_price_valid(price: float | None) -> bool:
        return price is not None and price > 0.0

    def _check_individual_stops(self, h: dict) -> list[RiskAlert]:
        alerts: list[RiskAlert] = []
        symbol = h["symbol"]
        name = h["name"]
        current = h["current_price"]
        entry = h["entry_price"]
        highest = h["highest_price"]
        hard_limit = h.get("stop_loss_hard", -0.20)
        trail_limit = h.get("stop_loss_trailing", -0.15)

        # Hard stop: drawdown from entry price
        hard_trigger = entry * (1.0 + hard_limit)
        if current <= hard_trigger:
            alerts.append(
                RiskAlert(
                    alert_type=self.ALERT_HARD,
                    symbol=symbol,
                    name=name,
                    current_price=current,
                    trigger_price=hard_trigger,
                    suggested_action=self.ACTION_MARKET_SELL,
                )
            )

        # Trailing stop: drawdown from highest price seen
        trail_trigger = highest * (1.0 + trail_limit)
        if current <= trail_trigger:
            alerts.append(
                RiskAlert(
                    alert_type=self.ALERT_TRAILING,
                    symbol=symbol,
                    name=name,
                    current_price=current,
                    trigger_price=trail_trigger,
                    suggested_action=self.ACTION_MARKET_SELL,
                )
            )

        return alerts

    def _check_portfolio_emergency(
        self, holdings: list[dict]
    ) -> list[RiskAlert]:
        if not holdings:
            return []

        total_entry_value = 0.0
        total_current_value = 0.0
        for h in holdings:
            weight = h.get("weight", 0.0)
            entry = h["entry_price"]
            current = h["current_price"]
            total_entry_value += weight
            total_current_value += weight * (current / entry)

        if total_entry_value <= 0:
            return []

        drawdown = 1.0 - (total_current_value / total_entry_value)
        portfolio_limit = abs(holdings[0].get("portfolio_stop_loss", -0.10))

        if drawdown >= portfolio_limit:
            return [
                RiskAlert(
                    alert_type=self.ALERT_PORTFOLIO,
                    symbol="PORTFOLIO",
                    name="组合净值",
                    current_price=round(total_current_value, 4),
                    trigger_price=round(total_entry_value * (1.0 - portfolio_limit), 4),
                    suggested_action=self.ACTION_REVIEW_IMMEDIATELY,
                )
            ]
        return []

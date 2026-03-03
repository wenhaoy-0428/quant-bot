"""Position sizing service.

Calculates optimal contract size and leverage for a new trade based on:
- Current account balance (via ExchangeService)
- Signal strength (trend score, confidence)
- Historical win rate (via PerformanceTracker)
- Risk management parameters (via Config)

This service replaces the four scattered helpers in ``main_bot.py``:
    _fetch_account_balance_usdt   → now in ExchangeService (no duplication)
    _compute_contracts             → private method here
    calculate_trend_based_position → merged into calculate_position_size()
    calculate_intelligent_position → removed (backward-compat duplicate)
"""

from typing import Optional

from core.config import config
from core.models.performance_tracker import PerformanceTracker, tracker
from core.services.exchange_service import ExchangeService, exchange_service


class PositionService:
    """Computes position size and leverage for an upcoming trade.

    Args:
        exchange:  Used only to fetch the current USDT balance.
        tracker:   Supplies the current win rate for adaptive sizing.
    """

    def __init__(
        self,
        exchange: ExchangeService,
        tracker: PerformanceTracker,
    ) -> None:
        self._exchange = exchange
        self._tracker = tracker

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_position_size(
        self,
        signal_data: dict,
        price_data: dict,
    ) -> dict:
        """Compute contract count, notional value, and optimal leverage.

        In ``main_bot.py`` this was split across two functions
        (``calculate_trend_based_position`` and the backward-compat
        ``calculate_intelligent_position``).  They're merged here because
        the signal dict always contains ``trend_score`` (defaulting to 0
        when absent), so there's no need for two separate code paths.

        Args:
            signal_data: The signal dict produced by the signal service.
                         Reads: ``stop_loss``, ``trend_score``, ``confidence``.
            price_data:  The enriched OHLCV dict from MarketDataService.
                         Reads: ``price``.

        Returns:
            dict with keys:
                contract_size    float  Number of contracts to open
                notional         float  Position notional value in USDT
                optimal_leverage int    Suggested leverage
                risk_pct         float  Fraction of capital risked
        """
        price = price_data.get("price")
        stop_loss_price = signal_data.get("stop_loss") or price * 0.99

        base_risk = self._tracker.get_dynamic_base_risk(config)
        trend_score = signal_data.get("trend_score", 0)
        confidence = signal_data.get("confidence", "MEDIUM").upper()

        # Scale risk up/down based on trend strength and AI confidence.
        # Capped between 0.5× and 1.5× the base risk.
        risk_multiplier = 1.0
        if trend_score >= 8:
            risk_multiplier += 0.2
        elif trend_score <= 5:
            risk_multiplier -= 0.2

        if confidence == "HIGH":
            risk_multiplier += 0.1
        elif confidence == "LOW":
            risk_multiplier -= 0.1

        risk_multiplier = max(0.5, min(1.5, risk_multiplier))
        risk_pct = max(0.001, base_risk * risk_multiplier)

        contracts, notional = self._compute_contracts(price, stop_loss_price, risk_pct)
        optimal_leverage = self._tracker.get_dynamic_leverage(config)

        return {
            "contract_size": contracts,
            "notional": notional,
            "optimal_leverage": optimal_leverage,
            "risk_pct": risk_pct,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_contracts(
        self,
        price: float,
        stop_loss_price: float,
        risk_pct: float,
    ) -> tuple[float, float]:
        """Compute contract count and notional from price/stop distance and risk %.

        Returns:
            (contracts, notional_usdt)
        """
        price = max(price, 1e-6)
        stop_loss_pct = (
            abs(price - stop_loss_price) / price if stop_loss_price else 0.01
        )
        stop_loss_pct = max(stop_loss_pct, 0.001)

        free_usdt, total_usdt = self._exchange.fetch_account_balance_usdt()
        max_util = config.max_capital_utilization

        # Dollar risk and notional, capped by max utilisation
        risk_usdt = total_usdt * risk_pct
        max_notional = total_usdt * max_util * config.leverage
        notional = risk_usdt / stop_loss_pct
        notional = max(0.0, min(notional, max_notional))

        contract_value = config.contract_size * price
        contracts = notional / contract_value if contract_value else 0.0
        contracts = max(contracts, config.min_amount)

        # Soft-cap if the account is already over the target utilisation
        current_util = (
            (total_usdt - free_usdt) / total_usdt if total_usdt > 0 else 0
        )
        if current_util > config.target_capital_utilization:
            contracts *= 0.8

        return contracts, notional


# Module-level singleton — wired together at import time.
# TradeService and main.py import this directly.
# Uses the shared tracker singleton from performance_tracker so all services
# read from the same win_rate and trade counts.
position_service = None

def initialize(exchange, track=tracker):
    global position_service
    if position_service is None:
        position_service = PositionService(exchange, track)
    return position_service

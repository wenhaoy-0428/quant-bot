"""Performance tracking model.

Replaces the bare ``performance_tracker`` dict and the free functions in
``main_bot.py`` that read/write it (``update_trade_result``,
``check_trading_conditions``, ``get_dynamic_leverage``,
``get_dynamic_base_risk``).

A single ``PerformanceTracker`` instance holds all runtime trade stats and
exposes a clean interface — no global dict mutation, no scattered helpers.
"""

from datetime import datetime
from typing import Optional


class PerformanceTracker:
    """Tracks live trade results and exposes adaptive risk parameters.

    Attributes are the same fields that lived in the old ``performance_tracker``
    dict, but now managed through explicit methods.
    """

    def __init__(self) -> None:
        self.trade_count: int = 0
        self.win_count: int = 0
        self.loss_count: int = 0
        self.win_rate: float = 0.0
        self.trade_results: list = []      # Rolling last-50 results for the dashboard
        self.daily_pnl: float = 0.0
        self.daily_trade_count: int = 0
        self.last_trade_time: Optional[datetime] = None
        self.last_trade_date: Optional[datetime.date] = None   # type: ignore[type-arg]
        self.is_trading_paused: bool = False

    # ------------------------------------------------------------------
    # Recording trades
    # ------------------------------------------------------------------

    def record_trade(self, is_win: bool, pnl: float = 0.0) -> None:
        """Record the result of a completed trade and update all derived stats."""
        self.trade_count += 1
        if is_win:
            self.win_count += 1
        else:
            self.loss_count += 1

        self.daily_pnl += pnl

        # Keep a short rolling history for the dashboard
        self.trade_results.append({
            "result": "win" if is_win else "loss",
            "pnl": pnl,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        self.trade_results = self.trade_results[-50:]

        self.win_rate = round(self.win_count / self.trade_count, 4)

    # ------------------------------------------------------------------
    # Trading gate
    # ------------------------------------------------------------------

    def is_trading_allowed(self, config) -> bool:
        """Return True if conditions allow a new trade.

        Checks the daily PnL threshold and the manual pause flag.
        Resets daily counters automatically at day rollover.

        Args:
            config: A ``Config`` instance (or any object with
                    ``daily_pnl_threshold`` attribute).
        """
        today = datetime.now().date()

        # Reset daily counters when the calendar date changes
        if self.last_trade_date and self.last_trade_date != today:
            self.daily_pnl = 0.0
            self.daily_trade_count = 0
            self.is_trading_paused = False
            self.last_trade_date = today

        if self.is_trading_paused:
            print("⏸️ 交易已暂停，等待手动恢复")
            return False

        if self.daily_pnl <= config.daily_pnl_threshold:
            self.is_trading_paused = True
            print(
                f"🛑 达到当日最大回撤限制({config.daily_pnl_threshold:.2%})，暂停交易"
            )
            return False

        return True

    def mark_trade_executed(self) -> None:
        """Update counters after a BUY/SELL order is sent."""
        now = datetime.now()
        self.last_trade_time = now
        self.last_trade_date = now.date()
        self.daily_trade_count += 1
        print(f"📊 交易频率记录：今日已交易{self.daily_trade_count}笔")

    # ------------------------------------------------------------------
    # Adaptive risk / leverage helpers
    # ------------------------------------------------------------------

    def get_dynamic_leverage(self, config) -> int:
        """Return optimal leverage based on current win rate.

        Args:
            config: A ``Config`` instance with ``min_leverage``, ``max_leverage``,
                    ``leverage`` (base) attributes.
        """
        min_lev = config.min_leverage
        max_lev = config.max_leverage
        base_lev = config.leverage

        if self.trade_count == 0:
            return base_lev  # Not enough data yet

        if self.win_rate >= 0.60:
            return min(max_lev, max(base_lev + 2, min_lev))
        if self.win_rate >= 0.40:
            return min(max_lev, max(base_lev, min_lev))
        return max(min_lev, base_lev - 2)

    def get_dynamic_base_risk(self, config) -> float:
        """Return optimal per-trade risk fraction based on current win rate.

        Args:
            config: A ``Config`` instance with ``get_risk_levels()`` and
                    ``base_risk_per_trade`` attributes.
        """
        if self.trade_count == 0:
            return config.base_risk_per_trade

        levels = config.get_risk_levels()
        high = levels.get("high_win_rate", {})
        med = levels.get("medium_win_rate", {})
        low = levels.get("low_win_rate", {})

        if self.win_rate >= high.get("threshold", 0.6):
            return high.get("min_risk", 0.05)
        if self.win_rate >= med.get("threshold", 0.4):
            return med.get("min_risk", 0.03)
        return low.get("min_risk", 0.01)


# Shared singleton — all services import this one instance so win_rate,
# trade counts, and daily PnL are consistent across the entire application.
tracker = PerformanceTracker()

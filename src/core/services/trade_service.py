"""Trade execution service.

Orchestrates the full trade lifecycle: position checks, direction logic,
order placement, and result recording.

The key structural improvement over ``main_bot.py``:
``execute_buy_logic`` and ``execute_sell_logic`` were ~250 lines each but
structurally identical — the only difference was which ccxt ``side`` string
('buy'/'sell') was used. They're merged here into a single
``_adjust_position()`` private method (~80 lines), parameterised by direction.

Responsibilities:
- ``execute_trade()``   — outer orchestrator (replaces execute_intelligent_trade)
- ``close_position()``  — full close with PnL accounting
- ``_adjust_position()``— open / add to / reduce a position in one direction
- ``_should_close()``   — signal-based exit check (replaces should_close_existing_position)
- ``trade_log``         — rolling record of AI decisions (replaces the global
                          trade_operations list)
"""

import time
import traceback
from datetime import datetime
from typing import Optional

from core.config import config
from core.models.performance_tracker import PerformanceTracker, tracker
from core.models.price_monitor import PriceMonitor
from core.services.exchange_service import ExchangeService, exchange_service
from core.services.position_service import PositionService, position_service

# Signal service still lives in trading_bots — imported directly.
from trading_bots.signals import should_execute_trade


class TradeService:
    """Executes trades on behalf of the main trading loop.

    Args:
        exchange:  Handles all raw OKX order calls.
        positions: Computes target contract size / leverage.
        tracker:   Records trade results and enforces daily limits.
        monitor:   Trailing-stop state for the open position (optional;
                   created fresh if not provided).
    """

    def __init__(
        self,
        exchange: ExchangeService,
        positions: PositionService,
        tracker: PerformanceTracker,
        monitor: Optional[PriceMonitor] = None,
    ) -> None:
        self._exchange = exchange
        self._positions = positions
        self._tracker = tracker
        self.price_monitor: PriceMonitor = monitor or PriceMonitor()
        # Rolling log of AI decisions — last 100 entries, used by dashboard
        self.trade_log: list = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_trade(self, signal_data: dict, price_data: dict) -> None:
        """Main entry point: evaluate signal and place orders if appropriate.

        Replaces ``execute_intelligent_trade`` from ``main_bot.py``.
        The logging of BB/trend context is collapsed into a helper to keep
        this method readable.
        """
        if not self._tracker.is_trading_allowed(config):
            return

        self._log_trade_context(signal_data, price_data)

        try:
            current_position = self._exchange.get_current_position()
            print(f"✅ 当前持仓: {current_position}")

            if not should_execute_trade(signal_data, price_data, current_position):
                print("⏸️ 交易条件不满足，跳过执行")
                return

            self._log_trend_strength(signal_data)

            position_result = self._positions.calculate_position_size(
                signal_data, price_data
            )
            position_size = position_result["contract_size"]
            optimal_leverage = position_result["optimal_leverage"]

            self._sync_leverage(optimal_leverage, current_position)
            self._log_decision(signal_data, position_size, optimal_leverage)

            action = signal_data["signal"]

            if action in ("BUY", "SELL"):
                self.price_monitor.update_position_info(
                    signal_data, price_data, position_size
                )
                if config.test_mode:
                    print("🧪 测试模式 - 仅模拟交易")
                else:
                    side = "buy" if action == "BUY" else "sell"
                    self._adjust_position(side, current_position, position_size, signal_data)

                self._tracker.mark_trade_executed()

            elif action == "HOLD":
                print("⏸️ 建议观望，不执行交易")
                if current_position and self._should_close(
                    signal_data, price_data, current_position
                ):
                    self.close_position(current_position)
                return

            print("✅ 交易执行完成")
            time.sleep(2)

            updated_position = self._exchange.get_current_position()
            print(f"📊 更新后持仓: {updated_position}")
            if not updated_position or updated_position["size"] == 0:
                self.price_monitor.clear_position_info()

        except Exception as exc:
            print(f"❌ 交易执行失败: {exc}")
            traceback.print_exc()

    def close_position(self, current_position: dict) -> None:
        """Fully close an open position and record the PnL.

        Cancels all pending TP/SL orders first to avoid orphaned orders.
        Replaces ``close_existing_position`` from ``main_bot.py``.
        """
        try:
            # Cancel TP/SL before closing so they don't fill after the flat
            try:
                print("🔄 平仓前强制取消该交易对的所有止盈止损订单...")
                self._exchange.cancel_tp_sl_orders(config.symbol, None)
                time.sleep(0.3)
            except Exception as exc:
                print(f"⚠️ 取消订单时出错（继续平仓）: {exc}")

            self.price_monitor.clear_position_info()

            actual_pnl = self._compute_close_pnl(current_position)
            is_win = actual_pnl > 0

            close_side = "sell" if current_position["side"] == "long" else "buy"
            self._exchange.create_market_order(
                config.symbol,
                close_side,
                current_position["size"],
                params={"reduceOnly": True},
            )
            print(f"✅ 已平掉{current_position['side']}仓")
            self._tracker.record_trade(is_win, actual_pnl)

        except Exception as exc:
            print(f"❌ 平仓失败: {exc}")
            try:
                self._exchange.cancel_tp_sl_orders(config.symbol, None)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _adjust_position(
        self,
        side: str,
        current_position: Optional[dict],
        target_size: float,
        signal_data: dict,
    ) -> None:
        """Open, add to, or reduce a position.

        This single method replaces the two ~250-line ``execute_buy_logic``
        and ``execute_sell_logic`` functions in ``main_bot.py``.  The
        directional symmetry is captured by two parameters:
            ``side``         — 'buy' (long) or 'sell' (short)
            ``opposite_side``— derived automatically

        Three cases, identical for longs and shorts:
        1. Existing position in the opposite direction → close it, open new
        2. Existing position in the same direction → size up or down
        3. No position → open fresh
        """
        opposite_side = "sell" if side == "buy" else "buy"
        position_side_name = "long" if side == "buy" else "short"
        trend_score = signal_data.get("trend_score", 0)
        confidence = signal_data.get("confidence", "MEDIUM")

        if current_position and current_position["side"] != position_side_name:
            # Reverse: close opposite, then open new
            if current_position["size"] > 0:
                print(
                    f"🔄 平{current_position['side']}仓 {current_position['size']:.2f} 张"
                    f" 并开{position_side_name}仓 {target_size:.2f} 张..."
                )
                self._exchange.create_market_order(
                    config.symbol,
                    opposite_side,
                    current_position["size"],
                    params={"reduceOnly": True},
                )
                self._log_operation(
                    f"平{current_position['side']}开{position_side_name}",
                    opposite_side,
                    current_position["size"],
                    f"信号反转 | 趋势: {signal_data.get('primary_trend', 'N/A')} ({trend_score}/10)",
                    confidence,
                    trend_score,
                )
                time.sleep(1)
            self._exchange.create_market_order(config.symbol, side, target_size)
            self._log_operation(
                f"开{position_side_name}仓",
                side,
                target_size,
                signal_data.get("reason", f"{side.upper()}信号"),
                confidence,
                trend_score,
            )

        elif current_position and current_position["side"] == position_side_name:
            # Same direction: adjust size
            size_diff = target_size - current_position["size"]

            # Special case: strong trend + high confidence → add minimum unit
            # even when size_diff is below threshold
            if (
                abs(size_diff) < 0.01
                and size_diff > 0
                and trend_score >= 8
                and confidence == "HIGH"
            ):
                min_contract = config.min_amount
                print(
                    f"🔥 强趋势({trend_score}/10)高信心({confidence})，"
                    f"执行最小单位加仓 {min_contract:.2f} 张"
                )
                self._exchange.create_market_order(config.symbol, side, min_contract)
                self._log_operation(
                    "强趋势加仓",
                    side,
                    min_contract,
                    f"强趋势({trend_score}/10)高信心({confidence}) | {signal_data.get('reason', '')[:100]}",
                    confidence,
                    trend_score,
                )

            elif abs(size_diff) >= 0.01:
                if size_diff > 0:
                    print(f"📈 {position_side_name}仓加仓 {size_diff:.2f} 张")
                    self._exchange.create_market_order(config.symbol, side, size_diff)
                    self._log_operation(
                        f"{position_side_name}仓加仓",
                        side,
                        size_diff,
                        f"仓位调整: {current_position['size']:.2f}→{target_size:.2f} | 趋势 {trend_score}/10",
                        confidence,
                        trend_score,
                    )
                else:
                    print(f"📉 {position_side_name}仓减仓 {abs(size_diff):.2f} 张")
                    self._exchange.create_market_order(
                        config.symbol,
                        opposite_side,
                        abs(size_diff),
                        params={"reduceOnly": True},
                    )
                    self._log_operation(
                        f"{position_side_name}仓减仓",
                        opposite_side,
                        abs(size_diff),
                        f"仓位调整: {current_position['size']:.2f}→{target_size:.2f} | 趋势 {trend_score}/10",
                        confidence,
                        trend_score,
                    )
            else:
                print(f"✅ {position_side_name}仓仓位合适，保持现状（已更新止损止盈）")
                self._log_operation(
                    "保持仓位",
                    position_side_name,
                    current_position["size"],
                    f"仓位已合适({current_position['size']:.2f}张) | 趋势 {trend_score}/10",
                    confidence,
                    trend_score,
                )

        else:
            # No position → open fresh
            print(f"📈 开{position_side_name}仓 {target_size:.2f} 张...")
            self._exchange.create_market_order(config.symbol, side, target_size)
            self._log_operation(
                f"开{position_side_name}仓",
                side,
                target_size,
                signal_data.get("reason", f"{side.upper()}信号"),
                confidence,
                trend_score,
            )

    def _should_close(
        self, signal_data: dict, price_data: dict, current_position: dict
    ) -> bool:
        """Return True if the current position should be closed on a HOLD signal.

        Replaces ``should_close_existing_position`` from ``main_bot.py``.
        Checks for:
        - Trend bias conflict with position direction
        - RSI overbought/oversold extremes
        """
        side = current_position["side"]
        trend_bias = signal_data.get("trend_bias", "")
        rsi = price_data["technical_data"].get("rsi", 50)

        if side == "long" and trend_bias == "bearish":
            return True
        if side == "short" and trend_bias == "bullish":
            return True
        if side == "long" and rsi > 80:
            return True
        if side == "short" and rsi < 20:
            return True
        return False

    def _compute_close_pnl(self, current_position: dict) -> float:
        """Estimate actual PnL after fees for a position being closed.

        Uses the live ticker price where available, falls back to
        estimating from unrealized_pnl percentage.
        """
        pos_size = current_position.get("size", 0)
        entry_price = current_position.get("entry_price", 0)

        try:
            ticker = self._exchange.fetch_ticker(config.symbol)
            current_price = ticker["last"]
        except Exception:
            unrealized_pnl_pct = current_position.get("unrealized_pnl", 0)
            direction = 1 if current_position["side"] == "long" else -1
            current_price = entry_price * (1 + direction * unrealized_pnl_pct / 100)

        notional = pos_size * config.contract_size * current_price
        total_fee = notional * config.trading_fee_rate

        unrealized_pnl_pct = current_position.get("unrealized_pnl", 0)
        pnl_amount = notional * (unrealized_pnl_pct / 100)
        actual_pnl = pnl_amount - total_fee
        actual_pnl_pct = (actual_pnl / notional * 100) if notional > 0 else 0

        print(
            f"💰 实际盈亏: 未实现={unrealized_pnl_pct:.2f}%, "
            f"手续费={total_fee:.4f} USDT ({config.trading_fee_rate*100:.2f}%), "
            f"实际={actual_pnl:.4f} USDT ({actual_pnl_pct:.2f}%)"
        )
        return actual_pnl

    def _sync_leverage(
        self, optimal_leverage: int, current_position: Optional[dict]
    ) -> int:
        """Update exchange leverage if it differs from the optimal value."""
        current_leverage = config.leverage
        if current_position and current_position.get("leverage"):
            current_leverage = int(current_position["leverage"])

        if optimal_leverage != current_leverage:
            try:
                self._exchange.set_leverage(optimal_leverage, config.symbol)
                config.leverage = optimal_leverage
                print(f"🔧 更新杠杆: {current_leverage}x → {optimal_leverage}x")
            except Exception as exc:
                print(f"⚠️ 更新杠杆失败: {exc}，继续使用 {current_leverage}x")
                optimal_leverage = current_leverage
        return optimal_leverage

    def _log_operation(
        self,
        action: str,
        side: str,
        amount: float,
        reason: str,
        confidence: str,
        trend_score: int,
    ) -> None:
        self.trade_log.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "side": side,
            "amount": amount,
            "reason": reason,
            "confidence": confidence,
            "trend_score": trend_score,
        })
        if len(self.trade_log) > 100:
            self.trade_log = self.trade_log[-100:]

    @staticmethod
    def _log_trade_context(signal_data: dict, price_data: dict) -> None:
        """Print the BB/trend context header (collapsed from ~50 lines in main_bot.py)."""
        trend_score = signal_data.get("trend_score", 0)
        bb_position = price_data["technical_data"].get("bb_position", 0.5)
        primary_trend = signal_data.get("primary_trend", "")

        if trend_score >= 7:
            trend_desc = "强趋势"
        elif trend_score >= 4:
            trend_desc = "中等趋势"
        else:
            trend_desc = "弱趋势"

        if bb_position < 0.1:
            structure = (
                "🚀 上涨趋势+布林带下轨 → 超卖反弹机会" if primary_trend == "强势上涨"
                else "📉 下跌趋势+布林带下轨 → 趋势加速确认" if primary_trend == "强势下跌"
                else "⚠️ 震荡趋势+布林带下轨 → 潜在反转信号"
            )
        elif bb_position > 0.9:
            structure = (
                "📈 上涨趋势+布林带上轨 → 趋势加速确认" if primary_trend == "强势上涨"
                else "🚀 下跌趋势+布林带上轨 → 超买回落机会" if primary_trend == "强势下跌"
                else "⚠️ 震荡趋势+布林带上轨 → 潜在反转信号"
            )
        elif bb_position < 0.2:
            structure = "📊 接近布林带下轨 → 弱势结构信号"
        elif bb_position > 0.8:
            structure = "📊 接近布林带上轨 → 强势结构信号"
        else:
            structure = "📈 布林带中部 → 正常结构条件"

        print("\n" + "=" * 60)
        print("🔥 开始执行交易流程...")
        print(f"📊 信号: {signal_data['signal']} | 信心: {signal_data['confidence']}")
        print(f"🎯 趋势: {primary_trend} ({trend_desc}, 强度: {trend_score}/10)")
        print(f"📊 布林带位置: {bb_position:.3f}")
        print(f"🔄 趋势-结构关系: {structure}")
        print(f"💰 当前价格: ${price_data['price']:,.2f}")
        print("=" * 60)

    @staticmethod
    def _log_trend_strength(signal_data: dict) -> None:
        trend_score = signal_data.get("trend_score", 0)
        action = signal_data["signal"]
        if action == "HOLD":
            return
        if trend_score >= 7:
            print(f"🚀 强趋势确认({trend_score}/10)，积极执行{action}信号")
        elif trend_score >= 5:
            print(f"📈 中等趋势({trend_score}/10)，正常执行{action}信号")
        else:
            print(f"⚠️ 弱趋势({trend_score}/10)，谨慎执行{action}信号")

    @staticmethod
    def _log_decision(
        signal_data: dict, position_size: float, leverage: int
    ) -> None:
        print(f"\n📋 交易决策:")
        print(f"   信号: {signal_data['signal']}")
        if "primary_trend" in signal_data:
            ts = signal_data.get("trend_score", 0)
            desc = "强趋势" if ts >= 7 else "中等趋势" if ts >= 4 else "弱趋势"
            print(f"   趋势: {signal_data['primary_trend']} ({desc}, 强度{ts}/10)")
        print(f"   信心: {signal_data['confidence']}")
        print(f"   仓位: {position_size:.2f} 张")
        print(f"   杠杆: {leverage}x")
        print(f"   理由: {signal_data['reason']}")
        print(f"   止损: {signal_data['stop_loss']:.2f}")
        print(f"   止盈: {signal_data['take_profit']:.2f}")


# Shared singleton — wired to the shared tracker and position_service.
trade_service = TradeService(
    exchange=exchange_service,
    positions=position_service,
    tracker=tracker,
)

"""Signal service.

The soldier signal pipeline: pure technical analysis → guidance filter →
stop-loss calculation.  Replaces the following functions from
``trading_bots/signals.py``:

Public:
  generate_signal_with_guidance  → SignalService.generate()
  should_execute_trade           → SignalService.should_execute()
  calculate_dynamic_stop_loss    → SignalService.calculate_stop_loss()  (public so AIService can reuse it)
  generate_trend_king_signal     → SignalService.generate_technical_signal()  (public for AIService)

Private helpers (used only within this class):
  enhanced_trend_analysis        → SignalService._enhanced_trend_analysis()
  structure_timing_signals       → SignalService._structure_timing_signals()
  apply_guidance_filter          → SignalService._apply_guidance_filter()

No AI calls live here — those belong in AIService.
"""

import os
from datetime import datetime
from typing import Optional

from core.config import config
from core.models.performance_tracker import PerformanceTracker, tracker
from trading_bots.guidance import load_guidance
from core.utils.indicators import calculate_volatility, detect_market_regime


class SignalService:
    """Generates the BTC/USDT 15-minute soldier signal.

    The main bot loop calls ``generate(price_data)`` each cycle.
    ``should_execute()`` gates whether the signal should trigger an order.
    ``signal_history`` is a rolling 30-entry list used inside ``should_execute``.

    Args:
        performance_tracker: Shared tracker for frequency-limiting checks.
    """

    def __init__(self, performance_tracker: PerformanceTracker) -> None:
        self._tracker = performance_tracker
        self.signal_history: list = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, price_data: dict, guidance: Optional[dict] = None) -> dict:
        """Generate a guidance-filtered signal with stop-loss attached.

        Reads ``guidance.json`` (written by ai_commander.py) unless an
        explicit ``guidance`` dict is passed (useful for backtests).
        """
        technical = self.generate_technical_signal(price_data)
        guidance = guidance or load_guidance()
        guided = self._apply_guidance_filter(technical, guidance)

        stop_loss, take_profit = self.calculate_stop_loss(guided, price_data)
        guided["stop_loss"] = stop_loss
        guided["take_profit"] = take_profit
        guided["timestamp"] = price_data.get("timestamp")

        self.signal_history.append(guided)
        if len(self.signal_history) > 30:
            self.signal_history.pop(0)

        return guided

    def generate_technical_signal(self, price_data: dict) -> dict:
        """Pure technical signal (no guidance, no AI).

        Exposed publicly so AIService can generate the technical baseline
        before adding the AI overlay.
        """
        return self._generate_trend_king_signal(price_data)

    def calculate_stop_loss(self, signal_data: dict, price_data: dict) -> tuple:
        """Compute ATR-based stop-loss and take-profit levels.

        Exposed publicly so AIService can call it after an AI response.

        Returns:
            (stop_loss_price, take_profit_price)
        """
        current_price = price_data["price"]
        atr = price_data["technical_data"].get("atr", current_price * 0.01)
        volatility = calculate_volatility(price_data["full_data"])
        trend_score = signal_data.get("trend_score", 0)

        if trend_score >= 8:
            sl_mult = float(os.getenv("SL_MULTIPLIER_HIGH", 1.2))
            tp_mult = float(os.getenv("TP_MULTIPLIER_HIGH", 3.0))
            print(f"📊 极强趋势({trend_score}/10)：止损{sl_mult}xATR，止盈{tp_mult}xATR")
        elif trend_score >= 6:
            sl_mult = float(os.getenv("SL_MULTIPLIER_MID", 1.5))
            tp_mult = float(os.getenv("TP_MULTIPLIER_MID", 2.5))
            print(f"📊 强趋势({trend_score}/10)：止损{sl_mult}xATR，止盈{tp_mult}xATR")
        else:
            sl_mult = float(os.getenv("SL_MULTIPLIER_LOW", 1.5))
            tp_mult = float(os.getenv("TP_MULTIPLIER_LOW", 2.0))
            print(f"📊 中等趋势({trend_score}/10)：止损{sl_mult}xATR，止盈{tp_mult}xATR")

        # Widen stop in high-volatility environments
        if volatility > 1.0:
            sl_mult += 0.3
        elif volatility < 0.3:
            sl_mult = max(sl_mult - 0.2, 0.5)

        is_buy = signal_data["signal"] == "BUY"
        if is_buy:
            stop_loss = current_price - atr * sl_mult
            take_profit = current_price + atr * tp_mult
        else:
            stop_loss = current_price + atr * sl_mult
            take_profit = current_price - atr * tp_mult

        # Enforce minimum stop distance (1.5%)
        min_stop = current_price * 0.015
        if abs(stop_loss - current_price) < min_stop:
            stop_loss = current_price * 0.985 if is_buy else current_price * 1.015

        # Ensure take-profit covers fees
        fee_buffer = config.trading_fee_rate + 0.0005
        if is_buy:
            min_tp = current_price * (1 + fee_buffer)
            if take_profit < min_tp:
                take_profit = min_tp
                print(f"⚠️ 止盈价已调整：确保覆盖手续费成本，新止盈价={take_profit:.2f}")
        else:
            min_tp = current_price * (1 - fee_buffer)
            if take_profit > min_tp:
                take_profit = min_tp
                print(f"⚠️ 止盈价已调整：确保覆盖手续费成本，新止盈价={take_profit:.2f}")

        print(
            f"🎯 动态风控: 止损={stop_loss:.2f}, 止盈={take_profit:.2f}, "
            f"ATR={atr:.2f} (已考虑手续费成本，使用智能止盈系统)"
        )
        return stop_loss, take_profit

    def should_execute(
        self,
        signal_data: dict,
        price_data: dict,
        current_position: Optional[dict],
    ) -> bool:
        """Return True if the signal should trigger an order.

        Checks RSI extremes, Bollinger-band conflicts, signal-history
        repetition, and trade-frequency limits.
        """
        tech = price_data["technical_data"]
        rsi = tech.get("rsi", 50)
        if rsi > 80 or rsi < 20:
            print(f"⚠️ RSI极端值({rsi:.1f})，暂停交易")
            return False

        bb_position = tech.get("bb_position", 0.5)
        trend_score = signal_data.get("trend_score", 0)
        primary_trend = signal_data.get("primary_trend", "")

        # Bollinger-band structure signal logging
        if bb_position < 0.1:
            bb_signal = "触及布林带下轨 - 超卖反弹机会" if primary_trend == "强势上涨" else "突破布林带下轨 - 趋势加速"
        elif bb_position > 0.9:
            bb_signal = "触及布林带上轨 - 超买回落机会" if primary_trend == "强势下跌" else "突破布林带上轨 - 趋势加速"
        elif bb_position < 0.2:
            bb_signal = "接近布林带下轨 - 潜在支撑"
        elif bb_position > 0.8:
            bb_signal = "接近布林带上轨 - 潜在阻力"
        else:
            bb_signal = "布林带中部 - 正常波动"
        print(f"📊 布林带结构信号: 位置{bb_position:.3f} → {bb_signal}")

        # Bollinger-band / trend conflict check
        should_pause = False
        pause_reason = ""
        if trend_score >= 7:
            if (primary_trend == "强势上涨" and bb_position < 0.1) or (primary_trend == "强势下跌" and bb_position > 0.9):
                should_pause = True
                pause_reason = f"强趋势{primary_trend}与布林带位置{bb_position:.3f}严重冲突"
            else:
                print(f"🎯 强趋势下的布林带结构信号: {bb_signal}")
        elif trend_score >= 4:
            if (primary_trend == "强势上涨" and bb_position < 0.05) or (primary_trend == "强势下跌" and bb_position > 0.95):
                should_pause = True
                pause_reason = f"中等趋势{primary_trend}与布林带极度位置{bb_position:.3f}冲突"
        else:
            if bb_position < 0.1 or bb_position > 0.9:
                print(f"⚠️ 弱趋势+布林带极端位置{bb_position:.3f}，可能反转，谨慎交易")

        if should_pause:
            print(f"⏸️ {pause_reason}，暂停交易")
            return False

        # Repeated low-confidence signal guard
        if len(self.signal_history) >= 2:
            last_two = [s["signal"] for s in self.signal_history[-2:]]
            if signal_data["signal"] in last_two and signal_data["confidence"] == "LOW":
                print("⚠️ 连续低信心相同信号，暂停执行")
                return False

        # Same-direction low-confidence guard
        if current_position:
            current_side = current_position["side"]
            signal_side = "long" if signal_data["signal"] == "BUY" else "short" if signal_data["signal"] == "SELL" else None
            if signal_side == current_side and signal_data["confidence"] == "LOW":
                print("⚠️ 同方向低信心信号，不调整仓位")
                return False

        # Trade-frequency limits (only relevant for non-HOLD signals)
        if signal_data["signal"] != "HOLD":
            now = datetime.now()
            today = now.date()

            # Reset daily counter at day rollover
            if self._tracker.last_trade_date and self._tracker.last_trade_date != today:
                self._tracker.daily_trade_count = 0
                self._tracker.last_trade_date = today
                print("📅 新的一天，重置每日交易计数")

            last_trade_time = self._tracker.last_trade_time
            if last_trade_time:
                hours_since = (now - last_trade_time).total_seconds() / 3600
                if hours_since < 2.0:
                    print(f"⏸️ 交易频率限制：距离上次交易仅{hours_since:.1f}小时，需等待至少2小时")
                    return False
            else:
                hours_since = 999

            daily_count = self._tracker.daily_trade_count
            if daily_count >= 10:
                print(f"⏸️ 交易频率限制：今日已交易{daily_count}笔，达到每日上限10笔")
                return False

            print(f"✅ 交易频率检查通过：距离上次交易{hours_since:.1f}小时，今日已交易{daily_count}笔")

        return True

    # ------------------------------------------------------------------
    # Private: technical analysis
    # ------------------------------------------------------------------

    def _generate_trend_king_signal(self, price_data: dict) -> dict:
        """Core signal logic based on the "趋势为王，结构修边" philosophy."""
        df = price_data["full_data"]
        latest_rsi = df["rsi"].iloc[-1] if "rsi" in df.columns else None
        funding_rate = price_data.get("funding_rate", 0.0) or 0.0

        trend_analysis = self._enhanced_trend_analysis(df)
        primary_trend = trend_analysis["primary_trend"]
        trend_score = trend_analysis["trend_score"]

        market_regime = detect_market_regime(df)
        structure_signals = self._structure_timing_signals(df, primary_trend)

        if market_regime == "ranging" and trend_score < 6:
            return {
                "signal": "HOLD",
                "reason": f"震荡市场且趋势不强(强度{trend_score}/10)，建议观望",
                "confidence": "LOW",
                "trend_score": trend_score,
                "primary_trend": primary_trend,
                "structure_signals": structure_signals,
                "structure_optimized": False,
                "risk_assessment": "高风险",
                "market_regime": market_regime,
            }

        entry_threshold = float(os.getenv("TREND_SCORE_ENTRY", 80)) / 10.0

        if trend_score >= entry_threshold:
            if primary_trend == "强势上涨":
                base_signal, base_conf = "BUY", "HIGH"
            elif primary_trend == "强势下跌":
                base_signal, base_conf = "SELL", "HIGH"
            else:
                base_signal, base_conf = "HOLD", "LOW"
        else:
            base_signal, base_conf = "HOLD", "LOW"

        funding_max = float(os.getenv("FUNDING_ABS_MAX", 0.0003))
        if abs(funding_rate) > funding_max:
            return {
                "signal": "HOLD",
                "reason": f"资金费率过高({funding_rate:.4%})，观望",
                "confidence": "LOW",
                "trend_score": trend_score,
                "primary_trend": primary_trend,
                "structure_signals": structure_signals,
                "structure_optimized": False,
                "risk_assessment": "高风险",
                "market_regime": market_regime,
            }

        rsi_buy_min = float(os.getenv("RSI_LONG_MIN", 45))
        rsi_buy_max = float(os.getenv("RSI_LONG_MAX", 75))
        rsi_sell_min = float(os.getenv("RSI_SHORT_MIN", 25))
        rsi_sell_max = float(os.getenv("RSI_SHORT_MAX", 55))

        rsi_ok_buy = latest_rsi is not None and rsi_buy_min <= latest_rsi <= rsi_buy_max
        rsi_ok_sell = latest_rsi is not None and rsi_sell_min <= latest_rsi <= rsi_sell_max
        funding_ok_buy = -0.0001 <= funding_rate <= 0.0002
        funding_ok_sell = -0.0002 <= funding_rate <= 0.0001

        filter_reason = None
        if base_signal == "BUY" and (not rsi_ok_buy or not funding_ok_buy):
            base_signal, base_conf = "HOLD", "LOW"
            filter_reason = (
                f"BUY条件未满足: RSI({latest_rsi:.1f} vs {rsi_buy_min}-{rsi_buy_max})"
                "或资金费率不在区间"
            )
        if base_signal == "SELL" and (not rsi_ok_sell or not funding_ok_sell):
            base_signal, base_conf = "HOLD", "LOW"
            filter_reason = (
                f"SELL条件未满足: RSI({latest_rsi:.1f} vs {rsi_sell_min}-{rsi_sell_max})"
                "或资金费率不在区间"
            )

        if base_signal != "HOLD" and structure_signals:
            if base_conf == "MEDIUM":
                base_conf = "HIGH"
            reason = f"趋势确认({primary_trend}, 强度{trend_score}/10)，结构信号:{', '.join(structure_signals)}"
            structure_optimized = True
        elif base_signal != "HOLD":
            if trend_score >= 8:
                base_signal, base_conf = "HOLD", "LOW"
                reason = f"极强趋势({primary_trend}, 强度{trend_score}/10)但无结构信号，等待更好入场时机"
                structure_optimized = False
            else:
                reason = f"趋势确认({primary_trend}, 强度{trend_score}/10)，等待更好结构时机"
                structure_optimized = False
        else:
            reason = filter_reason or f"趋势不明确(强度{trend_score}/10)，建议观望"
            structure_optimized = False

        return {
            "signal": base_signal,
            "reason": reason,
            "confidence": base_conf,
            "trend_score": trend_score,
            "primary_trend": primary_trend,
            "structure_signals": structure_signals,
            "structure_optimized": structure_optimized,
            "risk_assessment": (
                "低风险" if base_conf == "HIGH" else "中风险" if base_conf == "MEDIUM" else "高风险"
            ),
            "market_regime": market_regime,
        }

    @staticmethod
    def _enhanced_trend_analysis(df) -> dict:
        """MA + MACD + volume trend scoring ("趋势为王" trend-strength pass)."""
        s5, s20, s50 = df["sma_5"].iloc[-1], df["sma_20"].iloc[-1], df["sma_50"].iloc[-1]

        if s5 > s20 > s50:
            ma_trend = "强势上涨"
        elif s5 < s20 < s50:
            ma_trend = "强势下跌"
        else:
            ma_trend = "震荡"

        trend_score = 0
        if ma_trend in ("强势上涨", "强势下跌"):
            trend_score += 3

        current_price = df["close"].iloc[-1]
        if ma_trend == "强势上涨":
            if current_price > s20:
                trend_score += 2
            if current_price > s50:
                trend_score += 1
        elif ma_trend == "强势下跌":
            if current_price < s20:
                trend_score += 2
            if current_price < s50:
                trend_score += 1
        else:
            if current_price > s20:
                trend_score += 1

        macd = df["macd"].iloc[-1]
        macd_sig = df["macd_signal"].iloc[-1]
        macd_hist = df["macd_histogram"].iloc[-1]
        if ma_trend == "强势上涨":
            if macd > macd_sig:
                trend_score += 2
            if macd_hist > 0:
                trend_score += 1
        elif ma_trend == "强势下跌":
            if macd < macd_sig:
                trend_score += 2
            if macd_hist < 0:
                trend_score += 1
        else:
            if macd > macd_sig:
                trend_score += 1

        if df["volume_ratio"].iloc[-1] > 1.2:
            trend_score += 1

        if trend_score >= 7:
            trend_level, confidence = "强趋势", "高"
        elif trend_score >= 4:
            trend_level, confidence = "中等趋势", "中"
        else:
            trend_level, confidence = "弱趋势", "低"

        return {
            "primary_trend": ma_trend,
            "trend_score": trend_score,
            "trend_level": trend_level,
            "confidence": confidence,
            "current_price": current_price,
        }

    @staticmethod
    def _structure_timing_signals(df, primary_trend: str) -> list:
        """Find optimal entry timing based on micro-structure ("结构修边")."""
        current_price = df["close"].iloc[-1]
        signals = []

        rsi_long_min = float(os.getenv("RSI_LONG_MIN", 60))
        rsi_short_max = float(os.getenv("RSI_SHORT_MAX", 40))
        rsi_overbought = float(os.getenv("RSI_OVERBOUGHT", 55))
        rsi_oversold = float(os.getenv("RSI_OVERSOLD", 45))
        rsi = df["rsi"].iloc[-1]

        if primary_trend == "强势上涨":
            if current_price < df["sma_5"].iloc[-1] and rsi < rsi_long_min:
                signals.append("回踩5日线买入机会")
            if current_price < df["bb_middle"].iloc[-1] and df["bb_position"].iloc[-1] < 0.4:
                signals.append("回踩布林中轨买入机会")
            if df["macd_histogram"].iloc[-1] > df["macd_histogram"].iloc[-2] and df["macd_histogram"].iloc[-2] < 0:
                signals.append("MACD绿柱放大买入机会")
            if rsi < rsi_oversold and rsi > df["rsi"].iloc[-2]:
                signals.append("RSI超卖反弹买入机会")
        elif primary_trend == "强势下跌":
            if current_price > df["sma_5"].iloc[-1] and rsi > rsi_short_max:
                signals.append("反弹5日线做空机会")
            if current_price > df["bb_middle"].iloc[-1] and df["bb_position"].iloc[-1] > 0.6:
                signals.append("反弹布林中轨做空机会")
            if df["macd_histogram"].iloc[-1] < df["macd_histogram"].iloc[-2] and df["macd_histogram"].iloc[-2] > 0:
                signals.append("MACD红柱放大做空机会")
            if rsi > rsi_overbought and rsi < df["rsi"].iloc[-2]:
                signals.append("RSI超买回落做空机会")
            if current_price > df["sma_20"].iloc[-1] and rsi > 50:
                signals.append("反弹20日线做空机会")
            if df["bb_position"].iloc[-1] > 0.8:
                signals.append("布林带上轨阻力做空机会")

        return signals

    @staticmethod
    def _apply_guidance_filter(signal_data: dict, guidance: dict) -> dict:
        """Override the technical signal with commander guidance bias."""
        result = dict(signal_data)
        bias = str(guidance.get("bias", "NEUTRAL")).upper()
        vol_mode = str(guidance.get("volatility_mode", "STANDARD")).upper()

        if bias == "BULLISH" and result.get("signal") == "SELL":
            result["signal"] = "HOLD"
            result["confidence"] = "LOW"
            result["reason"] = f"{result.get('reason', '')} | 指挥: 偏多，阻止做空"
        elif bias == "BEARISH" and result.get("signal") == "BUY":
            result["signal"] = "HOLD"
            result["confidence"] = "LOW"
            result["reason"] = f"{result.get('reason', '')} | 指挥: 偏空，阻止做多"

        if vol_mode == "DEFENSIVE" and result.get("signal") != "HOLD":
            result["signal"] = "HOLD"
            result["confidence"] = "LOW"
            result["reason"] = f"{result.get('reason', '')} | 指挥: 防御模式，暂停开仓"

        result["ai_guidance"] = guidance
        return result


# Module-level singleton — shared across trading_bot.py and trade_service.py
signal_service = None

def initialize(performance_tracker=tracker):
    global signal_service
    if signal_service is None:
        signal_service = SignalService(performance_tracker)
    return signal_service

"""TradingBot — the top-level orchestrator.

``main.py`` creates one instance and calls ``run()``.  All trading logic
is delegated to the service layer; this class only owns:

- Startup sequence  (cleanup + position rehydration)
- The 15-minute timing loop
- One cycle of the trading pipeline (fetch → signal → execute)
- Graceful shutdown

Having a class here (rather than bare functions in main.py) makes it easy
to construct the bot with different parameters in the future:

    bot = TradingBot(symbol="ETH/USDT", timeframe="1h", dry_run=True)
"""

import sys
import time
from datetime import datetime

from core.config import config
from core.services.exchange_service import ExchangeService
from core.services.market_data_service import MarketDataService
from core.services.sentiment_service import SentimentService
from core.services.signal_service import SignalService
from core.services.trade_service import TradeService


class TradingBot:
    """Runs the BTC/USDT trend-following strategy on a 15-minute cadence.

    Args:
        exchange:    Exchange adapter.
        market_data: OHLCV + indicator service.
        trader:      Order execution service.
        sentiment:   Sentiment analysis service.
        signals:     Signal generation service.
    """

    def __init__(
        self,
        exchange: ExchangeService,
        market_data: MarketDataService,
        trader: TradeService,
        sentiment: SentimentService,
        signals: SignalService,
    ) -> None:
        self._exchange = exchange
        self._market_data = market_data
        self._trader = trader
        self._sentiment = sentiment
        self._signals = signals

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the bot: startup sequence, then loop forever on 15-min marks."""
        self._print_banner()

        if not self._exchange.exchange:
            print("❌ 交易所初始化失败")
            sys.exit(1)

        self._startup()
        print("🔄 开始主交易循环...")

        # First cycle runs immediately; subsequent ones wait for the next mark
        self._run_cycle(immediate=True)

        try:
            while True:
                self._run_cycle()
                time.sleep(60)
        except KeyboardInterrupt:
            print("🛑 程序被用户中断")
        finally:
            self._trader.price_monitor.stop_monitoring()

    # ------------------------------------------------------------------
    # Private: lifecycle
    # ------------------------------------------------------------------

    def _startup(self) -> None:
        """Cancel stale orders and rehydrate position monitor."""
        self._cleanup_stale_orders()
        initial_price_data = self._market_data.get_enriched_ohlcv()
        if initial_price_data:
            self._rehydrate_position(initial_price_data)

    def _cleanup_stale_orders(self) -> None:
        """Cancel any TP/SL orders left over from a previous run."""
        try:
            print("🔄 启动时清理所有残留的策略订单...")
            self._exchange.cancel_tp_sl_orders(config.symbol, None)
            print("✅ 残留订单清理完成")
        except Exception as exc:
            print(f"⚠️ 清理残留订单时出错（继续运行）: {exc}")

    def _rehydrate_position(self, price_data: dict) -> None:
        """Restore PriceMonitor tracking state for any open position."""
        try:
            pos = self._exchange.get_current_position()
            if pos and pos.get("size", 0) > 0:
                self._trader.price_monitor.initialize_existing_position(pos, price_data)
                print(f"✅ 已恢复现有持仓监控: {pos['size']} 合约")
        except Exception as exc:
            print(f"⚠️ 初始化现有持仓监控时出错: {exc}")

    # ------------------------------------------------------------------
    # Private: trading cycle
    # ------------------------------------------------------------------

    def _run_cycle(self, immediate: bool = False) -> None:
        """One complete trading cycle: wait → fetch → signal → execute."""
        if not immediate:
            wait = self._wait_for_next_15min()
            if wait > 0:
                time.sleep(wait)

        print("\n" + "=" * 60)
        print(f"🎯 趋势为王策略执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # 0. Sentiment API health check
        sentiment_health = self._sentiment.health_check()
        print(f"📊 市场情绪API状态: {sentiment_health}")
        if "不可用" in sentiment_health or "警告" in sentiment_health:
            print("⚠️ 市场情绪API异常，将仅基于技术分析进行交易决策")

        # 1. Fetch enriched OHLCV
        price_data = self._market_data.get_enriched_ohlcv()
        if not price_data:
            return

        # 2. Update trailing-stop with latest price
        monitor = self._trader.price_monitor
        if monitor and monitor.current_position_info:
            monitor.update_with_price(price_data["price"])

        print(f"BTC当前价格: ${price_data['price']:,.2f}")
        print(f"价格变化: {price_data['price_change']:+.2f}%")

        # 3. Generate signal (reads guidance.json written by ai_commander.py)
        signal_data = self._signals.generate(price_data)

        # 4. Execute trade
        self._trader.execute_trade(signal_data, price_data)

    # ------------------------------------------------------------------
    # Private: timing
    # ------------------------------------------------------------------

    @staticmethod
    def _wait_for_next_15min() -> int:
        """Return seconds until the next 15-minute mark and print a countdown."""
        now = datetime.now()
        minute, second = now.minute, now.second

        next_mark = ((minute // 15) + 1) * 15
        if next_mark == 60:
            next_mark = 0

        minutes_to_wait = (next_mark - minute) if next_mark > minute else (60 - minute + next_mark)
        seconds_to_wait = minutes_to_wait * 60 - second

        display_min = minutes_to_wait - 1 if second > 0 else minutes_to_wait
        display_sec = 60 - second if second > 0 else 0

        if display_min > 0:
            print(f"🕒 等待 {display_min} 分 {display_sec} 秒到整点...")
        else:
            print(f"🕒 等待 {display_sec} 秒到整点...")

        return seconds_to_wait

    # ------------------------------------------------------------------
    # Private: display
    # ------------------------------------------------------------------

    @staticmethod
    def _print_banner() -> None:
        print("🚀 BTC/USDT 趋势为王交易机器人启动")
        print("✅ 基于'趋势为王，结构修边'理念优化")
        print("🎯 核心特性: 趋势强度量化 + 结构时机优化 + 智能仓位管理")

"""Bot entry point."""

import sys
import traceback
from core.models.trading_bot import TradingBot
from core.services import (
    exchange_service,
    market_data_service,
    sentiment_service,
    signal_service,
    trade_service,
    position_service,
)
from core.models.performance_tracker import tracker

def main() -> None:
    try:
        print("🔄 初始化服务中...")
        
        # 1. Exchange (connects to API)
        exchange = exchange_service.initialize()
        
        # 2. Independent Services
        sentiment = sentiment_service.initialize()
        signals = signal_service.initialize(tracker)
        
        # 3. Dependent Services
        market_data = market_data_service.initialize(exchange)
        positions = position_service.initialize(exchange, tracker)
        trader = trade_service.initialize(exchange, positions, signals, tracker)
        
        print("✅ 服务初始化完成")
        
        # Instantiate and run bot
        bot = TradingBot(exchange, market_data, trader, sentiment, signals)
        bot.run()
        
    except Exception as e:
        print(f"❌ 服务初始化失败: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

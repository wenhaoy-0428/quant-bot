"""Market data service.

Fetches raw OHLCV candles from the exchange and enriches them with
technical indicators, trend analysis, and support/resistance levels.

This service is intentionally stateless — it holds no position or
performance state. That makes it safe to import from backtests and
the AI commander without side-effects.

The raw exchange call is delegated to ``ExchangeService``, so callers
never touch ccxt directly.
"""

import traceback
from datetime import datetime
from typing import Optional

import pandas as pd

from core.services.exchange_service import ExchangeService, exchange_service
from core.config import config
from core.utils.indicators import (
    calculate_technical_indicators,
    get_market_trend,
    get_support_resistance_levels,
)

_FUNDING_RATE_DEFAULT = 0.0


class MarketDataService:
    """Fetches and enriches OHLCV market data.

    ExchangeService handles the raw HTTP call; this class handles the
    domain transformation: DataFrame construction, indicator calculation,
    trend/support-resistance analysis, and packaging into the price_data
    dict that all other services consume.

    Args:
        exchange: An ``ExchangeService`` instance used for all raw API calls.
    """

    def __init__(self, exchange: ExchangeService) -> None:
        self._exchange = exchange

    def get_enriched_ohlcv(self) -> Optional[dict]:
        """Fetch OHLCV data and enrich with indicators and trend context.

        Returns a ``price_data`` dict on success, ``None`` if the exchange
        call fails.

        Return shape::

            price          float   Latest close price
            timestamp      str     Fetch time (local, %Y-%m-%d %H:%M:%S)
            high / low     float   Latest candle high/low
            volume         float   Latest candle volume
            timeframe      str     Candle interval from config
            price_change   float   % change vs previous close
            kline_data     list    Last 10 candles as dicts (dashboard chart)
            technical_data dict    Computed indicator values for latest candle
            trend_analysis dict    Output of get_market_trend()
            levels_analysis dict   Support/resistance levels
            funding_rate   float   Current perpetual funding rate (0.0 if unavailable)
            _df            DataFrame  Full enriched DataFrame (internal — do not
                                      depend on this outside market_data_service)
        """
        try:
            ohlcv = self._exchange.fetch_ohlcv(
                config.symbol,
                config.timeframe,
                limit=config.data_points,
            )
            if not ohlcv:
                print("⚠️ 未获取到有效K线数据")
                return None

            # Funding rate is best-effort — perpetual swaps always have one,
            # but the call can fail during maintenance or network issues.
            funding_rate = _FUNDING_RATE_DEFAULT
            try:
                funding_info = self._exchange.fetch_funding_rate(config.symbol)
                funding_rate = funding_info.get("fundingRate", _FUNDING_RATE_DEFAULT)
            except Exception as fetch_err:
                print(f"⚠️ 获取资金费率失败，使用默认值0: {fetch_err}")

            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

            df = calculate_technical_indicators(df)
            current = df.iloc[-1]
            previous = df.iloc[-2]

            trend_analysis = get_market_trend(df)
            levels_analysis = get_support_resistance_levels(df)

            return {
                "price": current["close"],
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "high": current["high"],
                "low": current["low"],
                "volume": current["volume"],
                "timeframe": config.timeframe,
                "price_change": (
                    (current["close"] - previous["close"]) / previous["close"] * 100
                ),
                "kline_data": (
                    df[["timestamp", "open", "high", "low", "close", "volume"]]
                    .tail(10)
                    .to_dict("records")
                ),
                "technical_data": {
                    "sma_5": current.get("sma_5", 0),
                    "sma_20": current.get("sma_20", 0),
                    "sma_50": current.get("sma_50", 0),
                    "rsi": current.get("rsi", 0),
                    "macd": current.get("macd", 0),
                    "macd_signal": current.get("macd_signal", 0),
                    "macd_histogram": current.get("macd_histogram", 0),
                    "bb_upper": current.get("bb_upper", 0),
                    "bb_lower": current.get("bb_lower", 0),
                    "bb_position": current.get("bb_position", 0),
                    "volume_ratio": current.get("volume_ratio", 0),
                    "atr": current.get("atr", 0),
                },
                "trend_analysis": trend_analysis,
                "levels_analysis": levels_analysis,
                "funding_rate": funding_rate,
                # Underscore prefix = internal field. The raw DataFrame is
                # needed by ai_commander and backtest scripts; callers outside
                # this package should not build logic against it.
                "_df": df,
            }

        except Exception as exc:
            print(f"获取增强K线数据失败: {exc}")
            traceback.print_exc()
            return None


# Shared singleton — import this directly instead of instantiating manually.
market_data_service = None

def initialize(exchange):
    global market_data_service
    if market_data_service is None:
        market_data_service = MarketDataService(exchange)
    return market_data_service

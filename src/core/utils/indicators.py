"""Technical analysis utility functions.

Pure, stateless pandas/numpy transforms used by multiple services:
  - MarketDataService  (calculate_technical_indicators, get_market_trend,
                        get_support_resistance_levels)
  - SignalService      (calculate_volatility, detect_market_regime)
  - AIService          (calculate_volatility)

Replaces ``trading_bots/indicators.py``.  No logic changes — same
algorithms, just moved into the src/ package tree.
"""

import numpy as np
import pandas as pd


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute ATR series with a rolling-mean fallback on failures."""
    try:
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        true_range = np.maximum(np.maximum(high_low, high_close), low_close)
        return true_range.rolling(period).mean()
    except Exception:
        return pd.Series([0] * len(df), index=df.index)


def calculate_volatility(df: pd.DataFrame, period: int = 20) -> float:
    """Annualised volatility based on percentage returns (15-minute candles)."""
    try:
        returns = df['close'].pct_change()
        volatility = returns.rolling(period).std() * np.sqrt(365 * 24 * 4)
        return float(volatility.iloc[-1])
    except Exception:
        return 0.0


def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Enhance an OHLCV dataframe with common indicators in-place."""
    try:
        df['sma_5'] = df['close'].rolling(window=5, min_periods=1).mean()
        df['sma_20'] = df['close'].rolling(window=20, min_periods=1).mean()
        df['sma_50'] = df['close'].rolling(window=50, min_periods=1).mean()

        df['ema_12'] = df['close'].ewm(span=12).mean()
        df['ema_26'] = df['close'].ewm(span=26).mean()
        df['macd'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']

        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        df['bb_middle'] = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']

        df['atr'] = calculate_atr(df)
        return df.bfill().ffill()
    except Exception:
        return df


def get_market_trend(df: pd.DataFrame) -> dict:
    """Summarise trend direction, strength, and price context."""
    try:
        current_price = df['close'].iloc[-1]
        trend_short = "上涨" if current_price > df['sma_20'].iloc[-1] else "下跌"
        trend_medium = "上涨" if current_price > df['sma_50'].iloc[-1] else "下跌"
        macd_trend = "bullish" if df['macd'].iloc[-1] > df['macd_signal'].iloc[-1] else "bearish"

        bb_position = df['bb_position'].iloc[-1]
        if bb_position > 0.7:
            price_level = "高位"
        elif bb_position < 0.3:
            price_level = "低位"
        else:
            price_level = "中位"

        if trend_short == "上涨" and trend_medium == "上涨":
            overall_trend = "强势上涨"
            trend_strength = "强"
        elif trend_short == "下跌" and trend_medium == "下跌":
            overall_trend = "强势下跌"
            trend_strength = "强"
        else:
            overall_trend = "震荡整理"
            trend_strength = "弱"

        return {
            'short_term': trend_short,
            'medium_term': trend_medium,
            'macd': macd_trend,
            'overall': overall_trend,
            'trend_strength': trend_strength,
            'price_level': price_level,
            'rsi_level': df['rsi'].iloc[-1],
            'bb_position': bb_position,
        }
    except Exception:
        return {}


def detect_market_regime(df: pd.DataFrame) -> str:
    """Identify whether the market is trending or ranging."""
    try:
        current_price = df['close'].iloc[-1]
        sma_20 = df['sma_20'].iloc[-1]
        sma_50 = df['sma_50'].iloc[-1]

        price_vs_sma20 = abs((current_price - sma_20) / sma_20) if sma_20 > 0 else 0
        price_vs_sma50 = abs((current_price - sma_50) / sma_50) if sma_50 > 0 else 0

        recent_high = df['high'].tail(20).max()
        recent_low = df['low'].tail(20).min()
        price_range_pct = (recent_high - recent_low) / recent_low if recent_low > 0 else 0

        sma_gap = abs((sma_20 - sma_50) / sma_50) if sma_50 > 0 else 0

        if (
            price_vs_sma20 < 0.005
            and price_vs_sma50 < 0.01
            and price_range_pct < 0.02
            and sma_gap < 0.01
        ):
            return 'ranging'
        return 'trending'
    except Exception:
        return 'trending'


def get_support_resistance_levels(df: pd.DataFrame, lookback: int = 20) -> dict:
    """Compute static and dynamic support/resistance levels."""
    try:
        recent_high = df['high'].tail(lookback).max()
        recent_low = df['low'].tail(lookback).min()
        current_price = df['close'].iloc[-1]

        return {
            'static_resistance': recent_high,
            'static_support': recent_low,
            'dynamic_resistance': df['bb_upper'].iloc[-1],
            'dynamic_support': df['bb_lower'].iloc[-1],
            'price_vs_resistance': ((recent_high - current_price) / current_price) * 100,
            'price_vs_support': ((current_price - recent_low) / recent_low) * 100,
        }
    except Exception:
        return {}

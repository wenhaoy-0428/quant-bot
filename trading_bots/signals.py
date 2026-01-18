import json
import os
import re
import time
import traceback
from datetime import datetime, timedelta

import pandas as pd
import requests

from trading_bots.config import (
    MODEL_NAME,
    TRADING_FEE_RATE,
    TRADE_CONFIG,
    deepseek_client,
    exchange,
    performance_tracker,
    signal_history,
)
from trading_bots.guidance import load_guidance
from trading_bots.indicators import calculate_volatility, detect_market_regime

# 市场情绪API监控状态
sentiment_api_monitor = {
    'last_check': None,
    'last_success': None,
    'consecutive_failures': 0,
    'is_available': True,
    'failure_count_today': 0,
    'last_error': None,
    'total_requests': 0,
    'successful_requests': 0,
    'last_reset_date': datetime.now().date()
}


def safe_json_parse(json_str):
    """安全解析JSON，处理格式不规范的情况"""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        try:
            # 修复常见的JSON格式问题
            json_str = json_str.replace("'", '"')
            json_str = re.sub(r'(\w+):', r"\"\1\":", json_str)
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            return json.loads(json_str)
        except json.JSONDecodeError as exc:
            print(f"JSON解析失败，原始内容: {json_str}")
            print(f"错误详情: {exc}")
            return None


def create_fallback_signal(price_data):
    """创建备用交易信号"""
    return {
        "signal": "HOLD",
        "reason": "因技术分析暂时不可用，采取保守策略",
        "stop_loss": price_data['price'] * 0.98,  # -2%
        "take_profit": price_data['price'] * 1.02,  # +2%
        "confidence": "LOW",
        "risk_assessment": "高风险",
        "is_fallback": True
    }


def enhanced_trend_analysis(df):
    """增强趋势分析 - 实现"趋势为王"理念"""
    ma_trend = "震荡"
    if df['sma_5'].iloc[-1] > df['sma_20'].iloc[-1] > df['sma_50'].iloc[-1]:
        ma_trend = "强势上涨"
    elif df['sma_5'].iloc[-1] < df['sma_20'].iloc[-1] < df['sma_50'].iloc[-1]:
        ma_trend = "强势下跌"

    trend_score = 0

    if ma_trend == "强势上涨":
        trend_score += 3
    elif ma_trend == "强势下跌":
        trend_score += 3

    current_price = df['close'].iloc[-1]
    if ma_trend == "强势上涨":
        if current_price > df['sma_20'].iloc[-1]:
            trend_score += 2
        if current_price > df['sma_50'].iloc[-1]:
            trend_score += 1
    elif ma_trend == "强势下跌":
        if current_price < df['sma_20'].iloc[-1]:
            trend_score += 2
        if current_price < df['sma_50'].iloc[-1]:
            trend_score += 1
    else:
        if current_price > df['sma_20'].iloc[-1]:
            trend_score += 1

    macd_value = df['macd'].iloc[-1]
    macd_signal = df['macd_signal'].iloc[-1]
    macd_histogram = df['macd_histogram'].iloc[-1]

    if ma_trend == "强势上涨":
        if macd_value > macd_signal:
            trend_score += 2
        if macd_histogram > 0:
            trend_score += 1
    elif ma_trend == "强势下跌":
        if macd_value < macd_signal:
            trend_score += 2
        if macd_histogram < 0:
            trend_score += 1
    else:
        if macd_value > macd_signal:
            trend_score += 1

    if df['volume_ratio'].iloc[-1] > 1.2:
        trend_score += 1

    if trend_score >= 7:
        trend_level = "强趋势"
        confidence = "高"
    elif trend_score >= 4:
        trend_level = "中等趋势"
        confidence = "中"
    else:
        trend_level = "弱趋势"
        confidence = "低"

    return {
        'primary_trend': ma_trend,
        'trend_score': trend_score,
        'trend_level': trend_level,
        'confidence': confidence,
        'current_price': current_price
    }


def structure_timing_signals(df, primary_trend, config=None):
    """结构修边 - 寻找优化入场时机"""
    current_price = df['close'].iloc[-1]
    signals = []

    # Default thresholds
    rsi_long_min = 60
    rsi_short_max = 40
    rsi_overbought = 55
    rsi_oversold = 45

    if config:
        rsi_long_min = config.get('rsi_long_min', 60)
        rsi_short_max = config.get('rsi_short_max', 40)
        rsi_overbought = config.get('rsi_overbought', 55)
        rsi_oversold = config.get('rsi_oversold', 45)
    else:
        rsi_long_min = float(os.getenv('RSI_LONG_MIN', 60))
        rsi_short_max = float(os.getenv('RSI_SHORT_MAX', 40))
        rsi_overbought = float(os.getenv('RSI_OVERBOUGHT', 55))
        rsi_oversold = float(os.getenv('RSI_OVERSOLD', 45))

    if primary_trend == "强势上涨":
        if current_price < df['sma_5'].iloc[-1] and df['rsi'].iloc[-1] < rsi_long_min:
            signals.append("回踩5日线买入机会")
        if current_price < df['bb_middle'].iloc[-1] and df['bb_position'].iloc[-1] < 0.4:
            signals.append("回踩布林中轨买入机会")
        if df['macd_histogram'].iloc[-1] > df['macd_histogram'].iloc[-2] and df['macd_histogram'].iloc[-2] < 0:
            signals.append("MACD绿柱放大买入机会")
        if df['rsi'].iloc[-1] < rsi_oversold and df['rsi'].iloc[-1] > df['rsi'].iloc[-2]:
            signals.append("RSI超卖反弹买入机会")

    elif primary_trend == "强势下跌":
        if current_price > df['sma_5'].iloc[-1] and df['rsi'].iloc[-1] > rsi_short_max:
            signals.append("反弹5日线做空机会")
        if current_price > df['bb_middle'].iloc[-1] and df['bb_position'].iloc[-1] > 0.6:
            signals.append("反弹布林中轨做空机会")
        if df['macd_histogram'].iloc[-1] < df['macd_histogram'].iloc[-2] and df['macd_histogram'].iloc[-2] > 0:
            signals.append("MACD红柱放大做空机会")
        if df['rsi'].iloc[-1] > rsi_overbought and df['rsi'].iloc[-1] < df['rsi'].iloc[-2]:
            signals.append("RSI超买回落做空机会")
        if current_price > df['sma_20'].iloc[-1] and df['rsi'].iloc[-1] > 50:
            signals.append("反弹20日线做空机会")
        if df['bb_position'].iloc[-1] > 0.8:
            signals.append("布林带上轨阻力做空机会")

    return signals


def generate_trend_king_signal(price_data, config=None):
    """基于"趋势为王，结构修边"理念生成交易信号"""
    df = price_data['full_data']
    latest_rsi = df['rsi'].iloc[-1] if 'rsi' in df.columns else None
    funding_rate = price_data.get('funding_rate', 0.0) or 0.0

    trend_analysis = enhanced_trend_analysis(df)
    primary_trend = trend_analysis['primary_trend']
    trend_score = trend_analysis['trend_score']

    market_regime = detect_market_regime(df)
    structure_signals = structure_timing_signals(df, primary_trend, config=config)

    if market_regime == 'ranging' and trend_score < 6:
        return {
            "signal": "HOLD",
            "reason": f"震荡市场且趋势不强(强度{trend_score}/10)，建议观望",
            "confidence": "LOW",
            "trend_score": trend_score,
            "primary_trend": primary_trend,
            "structure_signals": structure_signals,
            "structure_optimized": False,
            "risk_assessment": "高风险",
            "market_regime": market_regime
        }

    # Determine threshold from config (default 8.0, config is 0-100 scale)
    entry_threshold = 8.0
    if config:
        entry_threshold = config.get('trend_score_entry', 80) / 10.0
    else:
        entry_threshold = float(os.getenv('TREND_SCORE_ENTRY', 80)) / 10.0

    if trend_score >= entry_threshold:
        if primary_trend == "强势上涨":
            base_signal = "BUY"
            base_confidence = "HIGH"
        elif primary_trend == "强势下跌":
            base_signal = "SELL"
            base_confidence = "HIGH"
        else:
            base_signal = "HOLD"
            base_confidence = "LOW"
    else:
        base_signal = "HOLD"
        base_confidence = "LOW"

    filter_reason = None

    funding_max = 0.0003
    if config:
        funding_max = config.get('funding_abs_max', 0.0003)
    else:
        funding_max = float(os.getenv('FUNDING_ABS_MAX', 0.0003))

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
            "market_regime": market_regime
        }

    # Default thresholds
    rsi_buy_min = 45
    rsi_buy_max = 75
    rsi_sell_min = 25
    rsi_sell_max = 55
    
    if config:
        rsi_buy_min = config.get('rsi_long_min', 45)
        rsi_buy_max = config.get('rsi_long_max', 75)
        rsi_sell_min = config.get('rsi_short_min', 25)
        rsi_sell_max = config.get('rsi_short_max', 55)

    rsi_ok_buy = latest_rsi is not None and rsi_buy_min <= latest_rsi <= rsi_buy_max
    rsi_ok_sell = latest_rsi is not None and rsi_sell_min <= latest_rsi <= rsi_sell_max
    funding_ok_buy = -0.0001 <= funding_rate <= 0.0002
    funding_ok_sell = -0.0002 <= funding_rate <= 0.0001

    if base_signal == "BUY" and (not rsi_ok_buy or not funding_ok_buy):
        base_signal = "HOLD"
        base_confidence = "LOW"
        filter_reason = f"BUY条件未满足: RSI({latest_rsi:.1f} vs {rsi_buy_min}-{rsi_buy_max})或资金费率不在区间"
    if base_signal == "SELL" and (not rsi_ok_sell or not funding_ok_sell):
        base_signal = "HOLD"
        base_confidence = "LOW"
        filter_reason = f"SELL条件未满足: RSI({latest_rsi:.1f} vs {rsi_sell_min}-{rsi_sell_max})或资金费率不在区间"

    final_signal = base_signal
    final_confidence = base_confidence

    if base_signal != "HOLD" and structure_signals:
        if base_confidence == "MEDIUM":
            final_confidence = "HIGH"
        reason = f"趋势确认({primary_trend}, 强度{trend_score}/10)，结构信号:{', '.join(structure_signals)}"
        structure_optimized = True
    elif base_signal != "HOLD":
        if trend_score >= 8:
            final_signal = "HOLD"
            final_confidence = "LOW"
            reason = f"极强趋势({primary_trend}, 强度{trend_score}/10)但无结构信号，等待更好入场时机"
            structure_optimized = False
        else:
            reason = f"趋势确认({primary_trend}, 强度{trend_score}/10)，等待更好结构时机"
            structure_optimized = False
    else:
        reason = filter_reason or f"趋势不明确(强度{trend_score}/10)，建议观望"
        structure_optimized = False

    return {
        "signal": final_signal,
        "reason": reason,
        "confidence": final_confidence,
        "trend_score": trend_score,
        "primary_trend": primary_trend,
        "structure_signals": structure_signals,
        "structure_optimized": structure_optimized,
        "risk_assessment": "低风险" if final_confidence == "HIGH" else "中风险" if final_confidence == "MEDIUM" else "高风险",
        "market_regime": market_regime
    }


def apply_guidance_filter(signal_data, guidance):
    """Apply commander guidance on top of the technical soldier signal."""
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


def generate_signal_with_guidance(price_data, guidance=None, config=None):
    """Non-blocking soldier signal using cached commander guidance.

    Optional guidance override is accepted for backtests to avoid repeated file IO.
    """
    technical_signal = generate_trend_king_signal(price_data, config=config)
    guidance = guidance or load_guidance()
    guided_signal = apply_guidance_filter(technical_signal, guidance)

    stop_loss, take_profit = calculate_dynamic_stop_loss(guided_signal, price_data, config=config)
    guided_signal["stop_loss"] = stop_loss
    guided_signal["take_profit"] = take_profit
    guided_signal["timestamp"] = price_data.get("timestamp")

    signal_history.append(guided_signal)
    if len(signal_history) > 30:
        signal_history.pop(0)

    return guided_signal


def generate_technical_analysis_text(price_data):
    """生成技术分析文本"""
    if 'technical_data' not in price_data:
        return "技术指标数据不可用"

    tech = price_data['technical_data']
    trend = price_data.get('trend_analysis', {})
    levels = price_data.get('levels_analysis', {})

    def safe_float(value, default=0):
        return float(value) if value and pd.notna(value) else default

    analysis_text = f"""
    【技术指标分析】
    📈 移动平均线:
    - 5周期: {safe_float(tech['sma_5']):.2f} | 价格相对: {(price_data['price'] - safe_float(tech['sma_5'])) / safe_float(tech['sma_5']) * 100:+.2f}%
    - 20周期: {safe_float(tech['sma_20']):.2f} | 价格相对: {(price_data['price'] - safe_float(tech['sma_20'])) / safe_float(tech['sma_20']) * 100:+.2f}%
    - 50周期: {safe_float(tech['sma_50']):.2f} | 价格相对: {(price_data['price'] - safe_float(tech['sma_50'])) / safe_float(tech['sma_50']) * 100:+.2f}%

    🎯 趋势分析:
    - 短期趋势: {trend.get('short_term', 'N/A')}
    - 中期趋势: {trend.get('medium_term', 'N/A')}
    - 整体趋势: {trend.get('overall', 'N/A')}
    - MACD方向: {trend.get('macd', 'N/A')}

    📊 动量指标:
    - RSI: {safe_float(tech['rsi']):.2f} ({'超买' if safe_float(tech['rsi']) > 70 else '超卖' if safe_float(tech['rsi']) < 30 else '中性'})
    - MACD: {safe_float(tech['macd']):.4f}
    - 信号线: {safe_float(tech['macd_signal']):.4f}

    🎚️ 布林带位置: {safe_float(tech['bb_position']):.2%} ({'上部' if safe_float(tech['bb_position']) > 0.7 else '下部' if safe_float(tech['bb_position']) < 0.3 else '中部'})

    💰 关键水平:
    - 静态阻力: {safe_float(levels.get('static_resistance', 0)):.2f}
    - 静态支撑: {safe_float(levels.get('static_support', 0)):.2f}
    """
    return analysis_text


def get_sentiment_indicators():
    """获取市场情绪指标 - 带监控和降级处理"""
    global sentiment_api_monitor

    current_date = datetime.now().date()
    if sentiment_api_monitor['last_reset_date'] != current_date:
        sentiment_api_monitor['failure_count_today'] = 0
        sentiment_api_monitor['last_reset_date'] = current_date
        print("🔄 市场情绪API监控：每日计数器已重置")

    api_url = "https://service.cryptoracle.network/openapi/v2/endpoint"
    api_key = os.getenv('CRYPTORACLE_API_KEY', '')

    sentiment_api_monitor['last_check'] = datetime.now()
    sentiment_api_monitor['total_requests'] += 1

    if not api_key:
        print("⚠️ 市场情绪API密钥未配置，跳过情绪分析")
        sentiment_api_monitor['is_available'] = False
        return None

    if sentiment_api_monitor['consecutive_failures'] >= 5:
        print(f"⚠️ 市场情绪API连续失败{sentiment_api_monitor['consecutive_failures']}次，暂停使用")
        sentiment_api_monitor['is_available'] = False
        return None

    try:
        timeout = 10
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=4)

        request_body = {
            "apiKey": api_key,
            "endpoints": ["CO-A-02-01", "CO-A-02-02"],
            "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "timeType": "15m",
            "token": ["BTC"]
        }

        headers = {"Content-Type": "application/json", "X-API-KEY": api_key}
        response = requests.post(api_url, json=request_body, headers=headers, timeout=timeout)

        if response.status_code == 200:
            data = response.json()

            if data.get("code") == 200 and data.get("data"):
                time_periods = data["data"][0]["timePeriods"]

                for period in time_periods:
                    period_data = period.get("data", [])

                    sentiment = {}
                    valid_data_found = False

                    for item in period_data:
                        endpoint = item.get("endpoint")
                        value = item.get("value", "").strip()

                        if value:
                            try:
                                if endpoint in ["CO-A-02-01", "CO-A-02-02"]:
                                    sentiment[endpoint] = float(value)
                                    valid_data_found = True
                            except (ValueError, TypeError):
                                continue

                    if valid_data_found and "CO-A-02-01" in sentiment and "CO-A-02-02" in sentiment:
                        positive = sentiment['CO-A-02-01']
                        negative = sentiment['CO-A-02-02']
                        net_sentiment = positive - negative

                        data_delay = int((datetime.now() - datetime.strptime(
                            period['startTime'], '%Y-%m-%d %H:%M:%S')).total_seconds() // 60)

                        sentiment_api_monitor['consecutive_failures'] = 0
                        sentiment_api_monitor['is_available'] = True
                        sentiment_api_monitor['last_success'] = datetime.now()
                        sentiment_api_monitor['successful_requests'] += 1
                        sentiment_api_monitor['last_error'] = None

                        print(f"✅ 市场情绪API正常: 乐观{positive:.1%} 悲观{negative:.1%} 净值{net_sentiment:+.3f} (延迟:{data_delay}分钟)")

                        return {
                            'positive_ratio': positive,
                            'negative_ratio': negative,
                            'net_sentiment': net_sentiment,
                            'data_time': period['startTime'],
                            'data_delay_minutes': data_delay
                        }

                error_msg = "API返回数据为空"
                sentiment_api_monitor['consecutive_failures'] += 1
                sentiment_api_monitor['failure_count_today'] += 1
                sentiment_api_monitor['last_error'] = error_msg
                print(f"⚠️ 市场情绪API: {error_msg}")
                return None
            else:
                error_msg = f"API返回错误码: {data.get('code', 'unknown')}, 消息: {data.get('msg', 'unknown')}"
                sentiment_api_monitor['consecutive_failures'] += 1
                sentiment_api_monitor['failure_count_today'] += 1
                sentiment_api_monitor['last_error'] = error_msg
                print(f"⚠️ 市场情绪API: {error_msg}")
                return None
        else:
            error_msg = f"HTTP错误: {response.status_code}"
            sentiment_api_monitor['consecutive_failures'] += 1
            sentiment_api_monitor['failure_count_today'] += 1
            sentiment_api_monitor['last_error'] = error_msg
            print(f"⚠️ 市场情绪API: {error_msg}")
            return None

    except requests.exceptions.Timeout:
        error_msg = "请求超时（超过10秒）"
        sentiment_api_monitor['consecutive_failures'] += 1
        sentiment_api_monitor['failure_count_today'] += 1
        sentiment_api_monitor['last_error'] = error_msg
        print(f"⚠️ 市场情绪API: {error_msg}")
        return None

    except requests.exceptions.ConnectionError:
        error_msg = "连接错误（无法连接到服务器）"
        sentiment_api_monitor['consecutive_failures'] += 1
        sentiment_api_monitor['failure_count_today'] += 1
        sentiment_api_monitor['last_error'] = error_msg
        print(f"⚠️ 市场情绪API: {error_msg}")
        return None

    except Exception as exc:
        error_msg = f"未知错误: {str(exc)}"
        sentiment_api_monitor['consecutive_failures'] += 1
        sentiment_api_monitor['failure_count_today'] += 1
        sentiment_api_monitor['last_error'] = error_msg
        print(f"⚠️ 市场情绪API获取失败: {exc}")
        traceback.print_exc()
        return None


def check_sentiment_api_health():
    """检查市场情绪API健康状态"""
    global sentiment_api_monitor

    if sentiment_api_monitor['last_check'] is None:
        return "未检查"

    if not sentiment_api_monitor['is_available']:
        return f"不可用 (连续失败{sentiment_api_monitor['consecutive_failures']}次)"

    if sentiment_api_monitor['last_success']:
        time_since_success = (datetime.now() - sentiment_api_monitor['last_success']).total_seconds() / 60
        if time_since_success > 30:
            return f"警告 (上次成功: {time_since_success:.1f}分钟前)"

    success_rate = 0
    if sentiment_api_monitor['total_requests'] > 0:
        success_rate = (sentiment_api_monitor['successful_requests'] / sentiment_api_monitor['total_requests']) * 100

    return f"正常 (成功率: {success_rate:.1f}%, 今日失败: {sentiment_api_monitor['failure_count_today']}次)"


def calculate_dynamic_stop_loss(signal_data, price_data, config=None):
    """动态止损止盈计算"""
    current_price = price_data['price']
    atr = price_data['technical_data'].get('atr', current_price * 0.01)
    volatility = calculate_volatility(price_data['full_data'])

    trend_score = signal_data.get('trend_score', 0)

    if config:
        if trend_score >= 8:
            stop_loss_multiplier = config.get('sl_multiplier_high', 1.2)
            take_profit_multiplier = config.get('tp_multiplier_high', 3.0)
        elif trend_score >= 6:
            stop_loss_multiplier = config.get('sl_multiplier_mid', 1.5)
            take_profit_multiplier = config.get('tp_multiplier_mid', 2.5)
        else:
            stop_loss_multiplier = config.get('sl_multiplier_low', 1.5)
            take_profit_multiplier = config.get('tp_multiplier_low', 2.0)
    else:
        # Load from Environment if config object is missing
        if trend_score >= 8:
            stop_loss_multiplier = float(os.getenv('SL_MULTIPLIER_HIGH', 1.2))
            take_profit_multiplier = float(os.getenv('TP_MULTIPLIER_HIGH', 3.0))
            print(f"📊 极强趋势({trend_score}/10)：止损{stop_loss_multiplier}xATR，止盈{take_profit_multiplier}xATR")
        elif trend_score >= 6:
            stop_loss_multiplier = float(os.getenv('SL_MULTIPLIER_MID', 1.5))
            take_profit_multiplier = float(os.getenv('TP_MULTIPLIER_MID', 2.5))
            print(f"📊 强趋势({trend_score}/10)：止损{stop_loss_multiplier}xATR，止盈{take_profit_multiplier}xATR")
        else:
            stop_loss_multiplier = float(os.getenv('SL_MULTIPLIER_LOW', 1.5))
            take_profit_multiplier = float(os.getenv('TP_MULTIPLIER_LOW', 2.0))
            print(f"📊 中等趋势({trend_score}/10)：止损{stop_loss_multiplier}xATR，止盈{take_profit_multiplier}xATR")

    if volatility > 1.0:
        stop_loss_multiplier = stop_loss_multiplier + 0.3
    elif volatility < 0.3:
        stop_loss_multiplier = max(stop_loss_multiplier - 0.2, 0.5)

    atr_multiplier = stop_loss_multiplier

    if signal_data['signal'] == 'BUY':
        stop_loss = current_price - atr * atr_multiplier
        take_profit = current_price + atr * take_profit_multiplier
    else:
        stop_loss = current_price + atr * atr_multiplier
        take_profit = current_price - atr * take_profit_multiplier

    min_stop_distance = current_price * 0.015
    if abs(stop_loss - current_price) < min_stop_distance:
        if signal_data['signal'] == 'BUY':
            stop_loss = current_price * 0.985
        else:
            stop_loss = current_price * 1.015

    min_profit_distance = current_price * (TRADING_FEE_RATE + 0.0005)
    if signal_data['signal'] == 'BUY':
        min_take_profit = current_price * 1.0015
        if take_profit < min_take_profit:
            take_profit = min_take_profit
            print(f"⚠️ 止盈价已调整：确保覆盖手续费成本，新止盈价={take_profit:.2f}")
    else:
        min_take_profit = current_price * 0.9985
        if take_profit > min_take_profit:
            take_profit = min_take_profit
            print(f"⚠️ 止盈价已调整：确保覆盖手续费成本，新止盈价={take_profit:.2f}")

    print(f"🎯 动态风控: 止损={stop_loss:.2f}, 止盈={take_profit:.2f}, ATR={atr:.2f} (已考虑手续费成本，使用智能止盈系统)")
    return stop_loss, take_profit


def generate_technical_prompt(price_data):
    technical_analysis = generate_technical_analysis_text(price_data)

    sentiment_data = get_sentiment_indicators()
    if sentiment_data:
        sign = '+' if sentiment_data['net_sentiment'] >= 0 else ''
        sentiment_text = f"""
    【市场情绪】
    - 乐观比例: {sentiment_data['positive_ratio']:.1%}
    - 悲观比例: {sentiment_data['negative_ratio']:.1%}
    - 情绪净值: {sign}{sentiment_data['net_sentiment']:.3f}
    - 数据时间: {sentiment_data['data_time']} (延迟: {sentiment_data['data_delay_minutes']}分钟)
    """
    else:
        sentiment_text = """
    【市场情绪】
    - 数据暂不可用（API中断或配置问题，已自动降级为纯技术分析模式）
    """

    prompt = f"""
    你是一个专业的加密货币交易分析师。请基于以下BTC/USDT {TRADE_CONFIG['timeframe']}周期数据进行分析：

    {technical_analysis}

    【当前行情】
    - 当前价格: ${price_data['price']:,.2f}
    - 时间: {price_data['timestamp']}
    - 价格变化: {price_data['price_change']:+.2f}%
    - 波动率: {calculate_volatility(price_data['full_data']):.2%}
    {sentiment_text}

    【交易指导原则 - 必须遵守】
    1. **趋势优先**: 只在明确趋势中交易，避免震荡市频繁操作
    2. **风险控制**: 每笔交易风险控制在1-2%，使用ATR动态止损
    3. **信号确认**: 需要至少2个技术指标确认才发出交易信号
    4. **耐心等待**: 宁可错过不要做错，只在高质量机会出手

    【当前技术状况】
    - 整体趋势: {price_data['trend_analysis'].get('overall', 'N/A')}
    - 趋势强度: {price_data['trend_analysis'].get('trend_strength', 'N/A')}
    - 价格位置: {price_data['trend_analysis'].get('price_level', 'N/A')}
    - RSI: {price_data['technical_data'].get('rsi', 0):.1f}
    - 布林带位置: {price_data['technical_data'].get('bb_position', 0):.2%}

    【信号生成规则】
    - 强势上涨趋势 + RSI<70 → 高信心BUY
    - 强势下跌趋势 + RSI>30 → 高信心SELL  
    - 震荡整理 + 无明确方向 → HOLD
    - 任何极端指标(RSI>80/<20, 布林带极端) → HOLD

    请用以下JSON格式回复：
    {{
        "signal": "BUY|SELL|HOLD",
        "reason": "简要分析理由",
        "confidence": "HIGH|MEDIUM|LOW",
        "risk_assessment": "低风险|中风险|高风险"
    }}
    """
    return prompt


def analyze_with_deepseek(price_data):
    """增强版DeepSeek分析"""
    prompt = generate_technical_prompt(price_data)

    try:
        response = deepseek_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是指挥官，不是下单员。严格遵守：1) 绝不逆大势：若4H/1H趋势向上，谨慎建议做空；若4H/1H趋势向下，谨慎建议做多。"
                        "2) 仅在高质量结构信号下给出BUY/SELL/HOLD，不可自行调整风控阈值和仓位，参数调整交给Python执行。"
                        "3) 若市场处于极端波动/重大事件窗口，请优先建议HOLD并简要说明原因。"
                    )
                },
                {"role": "user", "content": prompt}
            ],
            stream=False,
            temperature=0.1
        )

        result = response.choices[0].message.content
        print(f"DeepSeek原始回复: {result}")

        start_idx = result.find('{')
        end_idx = result.rfind('}') + 1

        if start_idx != -1 and end_idx != 0:
            json_str = result[start_idx:end_idx]
            signal_data = safe_json_parse(json_str)
        else:
            signal_data = create_fallback_signal(price_data)

        if not all(field in signal_data for field in ['signal', 'reason', 'confidence', 'risk_assessment']):
            signal_data = create_fallback_signal(price_data)

        stop_loss, take_profit = calculate_dynamic_stop_loss(signal_data, price_data)
        signal_data['stop_loss'] = stop_loss
        signal_data['take_profit'] = take_profit

        signal_data['timestamp'] = price_data['timestamp']
        signal_history.append(signal_data)
        if len(signal_history) > 30:
            signal_history.pop(0)

        return signal_data

    except Exception as exc:
        print(f"DeepSeek分析失败: {exc}")
        return create_fallback_signal(price_data)


def build_trend_king_prompt(price_data, technical_signal):
    sentiment_data = get_sentiment_indicators()
    if sentiment_data:
        sign = '+' if sentiment_data['net_sentiment'] >= 0 else ''
        sentiment_text = f"""
    【市场情绪】
    - 乐观比例: {sentiment_data['positive_ratio']:.1%}
    - 悲观比例: {sentiment_data['negative_ratio']:.1%}
    - 情绪净值: {sign}{sentiment_data['net_sentiment']:.3f}
    - 数据时间: {sentiment_data['data_time']} (延迟: {sentiment_data['data_delay_minutes']}分钟)
    """
    else:
        sentiment_text = """
    【市场情绪】
    - 数据暂不可用（API中断或配置问题，已自动降级为纯技术分析模式）
    """

    bb_position = price_data['technical_data'].get('bb_position', 0)

    if technical_signal['trend_score'] >= 8:
        if (technical_signal['primary_trend'] == '强势上涨' and bb_position < 0.1) or (technical_signal['primary_trend'] == '强势下跌' and bb_position > 0.9):
            structure_relation = "趋势加速"
        else:
            structure_relation = "结构确认"
    else:
        structure_relation = "结构确认"

    prompt = f"""
    你是“指挥官”，负责BTC/USDT合约信号，必须执行对称的8条BUY/SELL规则。

    【当前数据】
    - 价格: ${price_data['price']:,.2f} | 变化: {price_data['price_change']:+.2f}% | 时间: {price_data['timestamp']}
    - RSI: {price_data['technical_data'].get('rsi', 0):.1f}
    - 布林带位置: {bb_position:.3f} (0=下轨,1=上轨)
    - MACD方向: {price_data['trend_analysis'].get('macd', 'N/A')}
    - 趋势: {technical_signal['primary_trend']} | 强度: {technical_signal['trend_score']}/10 | 结构: {', '.join(technical_signal['structure_signals']) if technical_signal['structure_signals'] else '无'}
    - 资金费率: {price_data.get('funding_rate', 0.0):.4%}
    - 波动率: {calculate_volatility(price_data['full_data']):.2%}
    {sentiment_text}

    【绝对禁止】
    - 逆4H趋势下单；框架<2个对齐；资金费率>|0.03%|；BUY RSI>75或<45；SELL RSI>55或<25；ATR>3x平均；重大事件前2小时。

    【BUY 8条 (全部满足才BUY，否则HOLD)】
    1) 4H: SMA5 > SMA20 > SMA50 且价> SMA50
    2) 1H: SMA5 > SMA20 且价> SMA20
    3) 15m: SMA5 上穿 SMA20 (黄金交叉)
    4) MACD: >Signal 或柱线转绿
    5) RSI: 45-75 区间
    6) 资金费率: -0.01% ~ +0.02%; +0.02~+0.03%减仓提示; >+0.03% 禁止
    7) 布林带位置: 0.3-0.7
    8) 成交量: 当前>20周期均量×1.2

    【SELL 8条 (全部满足才SELL，否则HOLD)】
    1) 4H: SMA5 < SMA20 < SMA50 且价< SMA50
    2) 1H: SMA5 < SMA20 且价< SMA20
    3) 15m: SMA5 下穿 SMA20 (死亡交叉)
    4) MACD: <Signal 或柱线转红
    5) RSI: 25-55 区间
    6) 资金费率: -0.02% ~ +0.01%; -0.03~-0.02%减仓提示; <-0.03% 禁止
    7) 布林带位置: 0.3-0.7
    8) 成交量: 当前>20周期均量×1.2

    【风控与收益】
    - 目标风险收益比≥1:2 (可至1:3)；止盈需包含0.15%手续费缓冲。
    - 输出仓位建议仅为相对强弱，最终下单由Python控制，不得改参数。

    按下列JSON回复，不要输出其他内容：
    {{
        "signal": "BUY|SELL|HOLD",
        "confidence": "HIGH|MEDIUM|LOW",
        "reason": "一句话原因，点出不满足的条目或满足的关键条目",
        "risk_assessment": "低风险|中风险|高风险",
        "stop_loss_pct": float,
        "take_profit_pct": float,
        "funding_rate": {price_data.get('funding_rate', 0.0):.6f},
        "rsi": {price_data['technical_data'].get('rsi', 0):.2f}
    }}
    """
    return prompt


def analyze_with_deepseek_trend_king(price_data):
    """基于趋势为王理念的DeepSeek分析"""
    technical_signal = generate_trend_king_signal(price_data)
    prompt = build_trend_king_prompt(price_data, technical_signal)

    try:
        response = deepseek_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": (
                    "你是指挥官，必须执行对称的BUY/SELL 8条规则，禁止逆大趋势、禁止越权修改风控参数。"
                    "小概率机会宁可HOLD，遇到资金费率极端、RSI越界、重大事件窗口或多时间框架不对齐时一律HOLD。"
                    "输出必须为JSON，字段完整且无额外文本。"
                )},
                {"role": "user", "content": prompt}
            ],
            stream=False,
            temperature=0.1
        )

        result = response.choices[0].message.content
        print(f"🎯 DeepSeek趋势为王分析回复: {result}")

        start_idx = result.find('{')
        end_idx = result.rfind('}') + 1
        if start_idx != -1 and end_idx != 0:
            json_str = result[start_idx:end_idx]
            signal_data = safe_json_parse(json_str)
        else:
            signal_data = technical_signal

        if not all(field in signal_data for field in ['signal', 'reason', 'confidence']):
            signal_data = technical_signal

        signal_data['trend_score'] = technical_signal['trend_score']
        signal_data['primary_trend'] = technical_signal['primary_trend']
        signal_data['structure_signals'] = technical_signal['structure_signals']
        signal_data['structure_optimized'] = technical_signal['structure_optimized']

        trend_score = technical_signal.get('trend_score', 0)
        technical_signal_type = technical_signal.get('signal', 'HOLD')

        if trend_score < 8:
            if signal_data.get('signal') != 'HOLD':
                print(f"🛑 强制HOLD：趋势强度{trend_score}/10 < 8，禁止AI覆盖技术信号")
                signal_data['signal'] = 'HOLD'
                signal_data['confidence'] = 'LOW'
                signal_data['reason'] = f"趋势强度{trend_score}/10 < 8，严格执行趋势强度过滤（技术信号：{technical_signal_type}，AI建议被拒绝）"
        elif technical_signal_type == 'HOLD' and trend_score >= 8:
            print(f"✅ 趋势强度{trend_score}/10 ≥ 8，允许AI分析覆盖技术信号HOLD")

        if 'risk_assessment' not in signal_data:
            signal_data['risk_assessment'] = technical_signal['risk_assessment']

        stop_loss, take_profit = calculate_dynamic_stop_loss(signal_data, price_data)
        signal_data['stop_loss'] = stop_loss
        signal_data['take_profit'] = take_profit

        signal_data['timestamp'] = price_data['timestamp']
        signal_history.append(signal_data)
        if len(signal_history) > 30:
            signal_history.pop(0)

        return signal_data

    except Exception as exc:
        print(f"❌ DeepSeek趋势为王分析失败: {exc}")
        traceback.print_exc()
        stop_loss, take_profit = calculate_dynamic_stop_loss(technical_signal, price_data)
        technical_signal['stop_loss'] = stop_loss
        technical_signal['take_profit'] = take_profit
        technical_signal['is_fallback'] = True
        return technical_signal


def analyze_with_deepseek_with_retry(price_data, max_retries=2):
    """带重试的DeepSeek分析"""
    for attempt in range(max_retries):
        try:
            signal_data = analyze_with_deepseek(price_data)
            if signal_data and not signal_data.get('is_fallback', False):
                return signal_data

            print(f"第{attempt + 1}次尝试失败，进行重试...")
            time.sleep(1)

        except Exception as exc:
            print(f"第{attempt + 1}次尝试异常: {exc}")
            if attempt == max_retries - 1:
                return create_fallback_signal(price_data)
            time.sleep(1)

    return create_fallback_signal(price_data)


def analyze_with_deepseek_trend_king_with_retry(price_data, max_retries=2):
    """带重试的趋势为王DeepSeek分析"""
    for attempt in range(max_retries):
        try:
            signal_data = analyze_with_deepseek_trend_king(price_data)
            if signal_data and not signal_data.get('is_fallback', False):
                return signal_data

            print(f"第{attempt + 1}次尝试失败，进行重试...")
            time.sleep(1)

        except Exception as exc:
            print(f"第{attempt + 1}次尝试异常: {exc}")
            if attempt == max_retries - 1:
                technical_signal = generate_trend_king_signal(price_data)
                stop_loss, take_profit = calculate_dynamic_stop_loss(technical_signal, price_data)
                technical_signal['stop_loss'] = stop_loss
                technical_signal['take_profit'] = take_profit
                technical_signal['is_fallback'] = True
                return technical_signal
            time.sleep(1)

    technical_signal = generate_trend_king_signal(price_data)
    stop_loss, take_profit = calculate_dynamic_stop_loss(technical_signal, price_data)
    technical_signal['stop_loss'] = stop_loss
    technical_signal['take_profit'] = take_profit
    technical_signal['is_fallback'] = True
    return technical_signal


def should_execute_trade(signal_data, price_data, current_position):
    """交易执行条件检查"""
    tech = price_data['technical_data']
    trend = price_data['trend_analysis']

    rsi = tech.get('rsi', 50)
    if rsi > 80 or rsi < 20:
        print(f"⚠️ RSI极端值({rsi:.1f})，暂停交易")
        return False

    bb_position = tech.get('bb_position', 0.5)
    trend_score = signal_data.get('trend_score', 0)
    primary_trend = signal_data.get('primary_trend', '')

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

    if len(signal_history) >= 2:
        last_signals = [s['signal'] for s in signal_history[-2:]]
        if signal_data['signal'] in last_signals and signal_data['confidence'] == 'LOW':
            print("⚠️ 连续低信心相同信号，暂停执行")
            return False

    if current_position:
        current_side = current_position['side']
        signal_side = 'long' if signal_data['signal'] == 'BUY' else 'short' if signal_data['signal'] == 'SELL' else None

        if signal_side == current_side and signal_data['confidence'] == 'LOW':
            print("⚠️ 同方向低信心信号，不调整仓位")
            return False

    if signal_data['signal'] != 'HOLD':
        now = datetime.now()
        current_date = now.date()

        if performance_tracker.get('last_trade_date') != current_date:
            performance_tracker['daily_trade_count'] = 0
            performance_tracker['last_trade_date'] = current_date
            print(f"📅 新的一天，重置每日交易计数")

        last_trade_time = performance_tracker.get('last_trade_time')
        if last_trade_time:
            time_since_last_trade = (now - last_trade_time).total_seconds() / 3600
            if time_since_last_trade < 2.0:
                print(f"⏸️ 交易频率限制：距离上次交易仅{time_since_last_trade:.1f}小时，需等待至少2小时")
                return False
        else:
            time_since_last_trade = 999

        daily_trade_count = performance_tracker.get('daily_trade_count', 0)
        if daily_trade_count >= 10:
            print(f"⏸️ 交易频率限制：今日已交易{daily_trade_count}笔，达到每日上限10笔")
            return False

        print(f"✅ 交易频率检查通过：距离上次交易{time_since_last_trade:.1f}小时，今日已交易{daily_trade_count}笔")

    return True

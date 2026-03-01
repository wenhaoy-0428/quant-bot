"""Dashboard helper functions for the trading bot.

All trading logic has been migrated to ``src/``:
- PriceMonitor             → src/core/models/price_monitor.py
- PerformanceTracker       → src/core/models/performance_tracker.py
- MarketDataService        → src/core/services/market_data_service.py
- PositionService          → src/core/services/position_service.py
- TradeService             → src/core/services/trade_service.py
- Main loop / entry point  → src/app/main.py

This file retains only the three dashboard export helpers that have not yet
been migrated (pending future dashboard service work):
- get_or_set_initial_balance()
- get_recent_trades()
- export_dashboard_data()

Known limitations in the retained functions (pre-existing):
- ``INITIAL_BALANCE_FILE`` and ``DASHBOARD_DATA_FILE`` are not defined here;
  they need to be supplied before calling export_dashboard_data().
- ``get_dynamic_leverage`` and ``get_dynamic_base_risk`` are referenced inside
  export_dashboard_data but removed from this file; import them from
  ``src.core.models.performance_tracker`` when this is wired up.
- ``price_monitor`` and ``trade_operations`` globals are referenced but no
  longer set here; they live in ``src.core.services.trade_service``.
"""

import fcntl
import json
import os
import sys
import traceback
from datetime import datetime

from trading_bots.config import (
    TRADE_CONFIG,
    exchange,
    performance_tracker,
    signal_history,
)
from trading_bots.execution import get_current_position


def get_or_set_initial_balance(current_balance):
    """获取或设置初始资金"""
    try:
        # 尝试读取初始资金配置
        if os.path.exists(INITIAL_BALANCE_FILE):
            with open(INITIAL_BALANCE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('initial_balance', current_balance)
        else:
            # 如果不存在，使用当前余额作为初始值并保存
            initial_data = {
                'initial_balance': current_balance,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            os.makedirs(os.path.dirname(INITIAL_BALANCE_FILE), exist_ok=True)
            with open(INITIAL_BALANCE_FILE, 'w', encoding='utf-8') as f:
                json.dump(initial_data, f, ensure_ascii=False, indent=2)
            print(f"📝 初始资金已设置: {current_balance:.2f} USDT")
            return current_balance
    except Exception as e:
        print(f"⚠️ 读取初始资金失败，使用当前余额: {e}")
        return current_balance

def get_recent_trades(limit=50):
    """获取最近的交易历史"""
    try:
        # 使用fetch_my_trades获取成交记录（OKX不支持fetch_orders）
        trades = exchange.fetch_my_trades(TRADE_CONFIG['symbol'], limit=limit)
        
        trade_history = []
        for trade in trades:
            trade_history.append({
                'trade_id': trade['id'],
                'order_id': trade.get('order', 'N/A'),
                'timestamp': datetime.fromtimestamp(trade['timestamp']/1000).strftime('%Y-%m-%d %H:%M:%S') if trade['timestamp'] else 'N/A',
                'side': trade['side'],  # 'buy' or 'sell'
                'type': trade.get('type', 'market'),
                'price': trade['price'],
                'amount': trade['amount'],
                'cost': trade['cost'],
                'fee': trade.get('fee', {}).get('cost', 0) if trade.get('fee') else 0,
                'fee_currency': trade.get('fee', {}).get('currency', 'USDT') if trade.get('fee') else 'USDT'
            })
        
        # 按时间倒序排列（最新的在前）
        trade_history.reverse()
        return trade_history
        
    except Exception as e:
        print(f"⚠️ 获取交易历史失败: {e}")
        traceback.print_exc()
        return []

def export_dashboard_data(price_data, signal_data=None):
    """导出数据到Dashboard JSON文件"""
    global price_monitor
    try:
        # 获取当前持仓
        current_position = get_current_position()
        
        # 获取账户余额 - 使用total获取真实总资产（包含可用+保证金+盈亏）
        balance = exchange.fetch_balance()
        usdt_free = balance.get('USDT', {}).get('free', 0)  # 可用余额
        usdt_used = balance.get('USDT', {}).get('used', 0)  # 占用保证金
        usdt_total = balance.get('USDT', {}).get('total', 0)  # 真实总资产
        
        # 如果是测试模式，使用模拟余额
        if TRADE_CONFIG.get('test_mode', False):
            usdt_total = 10000.0  # 测试模式使用10000 USDT
            usdt_free = 10000.0
        
        # 使用OKX返回的total作为真实总资产（已经包含盈亏）
        total_value = usdt_total
        
        # 计算持仓名义价值（仅用于展示）
        position_notional = 0
        if current_position:
            # 名义价值 = 合约数量 * 合约乘数 * 当前价格
            position_notional = current_position['size'] * TRADE_CONFIG.get('contract_size', 0.01) * price_data['price']
        
        # 获取或设置初始资金
        initial_value = get_or_set_initial_balance(total_value)
        
        # 计算收益率
        if initial_value > 0:
            change_percent = ((total_value - initial_value) / initial_value) * 100
        else:
            change_percent = 0
        
        # 获取加密货币价格
        crypto_prices = {}
        try:
            symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'DOGE/USDT', 'XRP/USDT']
            for symbol in symbols:
                ticker = exchange.fetch_ticker(symbol)
                base_symbol = symbol.split('/')[0]
                crypto_prices[base_symbol] = {
                    'price': ticker['last'],
                    'change': ticker['percentage']
                }
        except Exception as e:
            print(f"获取加密货币价格失败: {e}")
        
        # 获取交易历史
        trade_history = get_recent_trades(limit=50)
        
        # 获取AI交易操作记录（最近50条）
        global trade_operations
        recent_operations = trade_operations[-50:] if trade_operations else []
        
        # 获取价格监控信息（止盈止损监控）
        price_monitor_info = None
        if price_monitor and price_monitor.current_position_info.get('position_side'):
            position_info = price_monitor.current_position_info
            current_price = price_data['price']
            
            # 计算当前盈亏
            if position_info['position_side'] == 'long':
                profit_pct = (current_price - position_info['entry_price']) / position_info['entry_price'] * 100
            else:  # short
                profit_pct = (position_info['entry_price'] - current_price) / position_info['entry_price'] * 100
            
            # 计算移动止盈触发价
            trailing_stop_price = None
            if position_info['trailing_stop_activated']:
                if position_info['position_side'] == 'long':
                    trailing_stop_price = position_info['highest_profit'] * 0.995
                else:  # short
                    trailing_stop_price = position_info['lowest_profit'] * 1.005
            
            price_monitor_info = {
                "entry_price": position_info['entry_price'],
                "stop_loss": position_info['stop_loss'],
                "take_profit": position_info['take_profit'],
                "current_profit_pct": round(profit_pct, 2),
                "trailing_stop_activated": position_info['trailing_stop_activated'],
                "trailing_stop_price": round(trailing_stop_price, 2) if trailing_stop_price else None,
                "highest_profit": position_info.get('highest_profit', 0) if position_info['position_side'] == 'long' else None,
                "lowest_profit": position_info.get('lowest_profit', 0) if position_info['position_side'] == 'short' else None,
                "peak_profit": round(position_info.get('peak_profit', 0), 2),
                "trailing_window": 0.5  # 回撤窗口0.5%
            }
        
        # 计算资金利用率
        capital_utilization = (usdt_used / total_value * 100) if total_value > 0 else 0
        max_utilization = TRADE_CONFIG['risk_management'].get('max_capital_utilization', 0.60) * 100
        min_utilization = TRADE_CONFIG['risk_management'].get('min_capital_utilization', 0.30) * 100
        
        # 获取动态杠杆（基于当前胜率）
        win_rate = performance_tracker.get('win_rate', 0)
        dynamic_leverage = get_dynamic_leverage(win_rate)
        current_leverage = TRADE_CONFIG.get('leverage', 6)  # 当前设置的杠杆
        
        # 获取交易胜率统计
        trade_count = performance_tracker.get('trade_count', 0)
        win_count = performance_tracker.get('win_count', 0)
        loss_count = performance_tracker.get('loss_count', 0)
        win_rate_pct = win_rate * 100 if win_rate else 0
        
        # 获取动态基础风险
        dynamic_base_risk = get_dynamic_base_risk(win_rate)
        dynamic_base_risk_pct = dynamic_base_risk * 100
        
        # 构建数据
        dashboard_data = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "account": {
                "balance": usdt_free,  # 可用余额
                "total_value": total_value,  # 真实总资产
                "change_percent": change_percent,
                "initial_balance": initial_value,
                "margin_used": usdt_used,  # 占用保证金
                "position_notional": position_notional,  # 持仓名义价值（仅供参考）
                "capital_utilization": round(capital_utilization, 2),  # 资金利用率（%）
                "max_capital_utilization": round(max_utilization, 2),  # 最大资金利用率（%）
                "min_capital_utilization": round(min_utilization, 2)  # 最小资金利用率（%）
            },
            "risk_management": {
                "current_leverage": current_leverage,  # 当前设置的杠杆
                "dynamic_leverage": dynamic_leverage,  # 动态杠杆（基于胜率）
                "base_risk_per_trade": round(TRADE_CONFIG['risk_management']['base_risk_per_trade'] * 100, 2),  # 基础风险（%）
                "dynamic_base_risk": round(dynamic_base_risk_pct, 2),  # 动态基础风险（%）
                "adaptive_risk_enabled": TRADE_CONFIG['risk_management'].get('adaptive_risk_enabled', False)
            },
            "performance_stats": {
                "win_rate": round(win_rate_pct, 2),  # 胜率（%）
                "trade_count": trade_count,  # 总交易次数
                "win_count": win_count,  # 盈利次数
                "loss_count": loss_count,  # 亏损次数
                "min_trades_for_adaptive": TRADE_CONFIG['risk_management'].get('min_trades_for_adaptive', 10),
                "adaptive_active": trade_count >= TRADE_CONFIG['risk_management'].get('min_trades_for_adaptive', 10)  # 是否已启用动态调整
            },
            "position": current_position,
            "signals": signal_history[-20:] if signal_history else [],  # 最近20个信号
            "trades": trade_history,  # 交易所成交历史
            "trade_operations": recent_operations,  # AI决策的加减仓操作记录
            "price_data": {
                "price": price_data['price'],
                "timestamp": price_data['timestamp'],
                "high": price_data['high'],
                "low": price_data['low'],
                "volume": price_data['volume'],
                "price_change": price_data['price_change']
            },
            "technical_analysis": {
                "rsi": price_data['technical_data'].get('rsi', 50),
                "macd": price_data['technical_data'].get('macd', 0),
                "trend": price_data['trend_analysis'].get('overall', '震荡整理'),
                "trend_strength": price_data['trend_analysis'].get('trend_strength', 'N/A'),
                "price_level": price_data['trend_analysis'].get('price_level', 'N/A')
            },
            "crypto_prices": crypto_prices,
            "price_monitor": price_monitor_info,  # 价格监控和止盈止损信息
            "performance_history": []  # 这个由Dashboard维护
        }
        
        # 写入文件（使用文件锁）
        with open(DASHBOARD_DATA_FILE, 'w', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # 排他锁
            json.dump(dashboard_data, f, ensure_ascii=False, indent=2)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # 释放锁
        
        print(f"✅ Dashboard数据已导出: {dashboard_data['timestamp']}")
        print(f"   - 总资产: {total_value:.2f} USDT")
        print(f"   - 收益率: {change_percent:+.2f}%")
        print(f"   - 资金利用率: {capital_utilization:.1f}% (目标: {min_utilization:.0f}%-{max_utilization:.0f}%)")
        print(f"   - 交易记录: {len(trade_history)} 条")
        print(f"   - 交易胜率: {win_rate_pct:.1f}% (总交易: {trade_count}, 盈利: {win_count}, 亏损: {loss_count})")
        print(f"   - 动态杠杆: {dynamic_leverage}x (当前设置: {current_leverage}x)")
        print(f"   - 动态基础风险: {dynamic_base_risk_pct:.1f}%")
        sys.stdout.flush()
        
    except Exception as e:
        print(f"❌ 导出Dashboard数据失败: {e}")
        traceback.print_exc()
        sys.stdout.flush()

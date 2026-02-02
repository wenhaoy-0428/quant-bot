#!/bin/bash

# ============================================
# 安全重启交易Bot（不影响现有持仓和订单）
# ============================================

echo "🔄 安全重启交易Bot..."
echo "========================================"

# 获取脚本所在目录作为项目根目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR" || exit 1

# 激活虚拟环境
source venv/bin/activate

# 检查当前持仓和订单状态
echo ""
echo "📊 检查当前状态..."
python3 -c "
import os
import sys
# sys.path.append(os.path.join(os.getcwd(), 'trading_bots'))
sys.path.append(os.getcwd())
from dotenv import load_dotenv
import ccxt
load_dotenv()

exchange = ccxt.okx({
    'options': {'defaultType': 'swap'},
    'apiKey': os.getenv('OKX_API_KEY'),
    'secret': os.getenv('OKX_SECRET'),
    'password': os.getenv('OKX_PASSWORD'),
})

# 检查持仓
positions = exchange.fetch_positions(['BTC/USDT:USDT'])
has_position = False
for pos in positions:
    if pos['symbol'] == 'BTC/USDT:USDT' and float(pos.get('contracts', 0)) > 0:
        has_position = True
        print(f\"✅ 发现持仓: {pos['side']} {pos['contracts']} 张, 入场价: {pos.get('entryPrice', 'N/A')}\")

if not has_position:
    print('ℹ️  当前无持仓')

# 检查未完成订单
orders = exchange.fetch_open_orders('BTC/USDT:USDT')
print(f\"📋 未完成订单: {len(orders)} 个\")
if orders:
    for order in orders[:3]:
        print(f\"   - {order['type']} {order['side']} @ {order.get('price', 'market')}\")
" 2>&1

echo ""
echo "========================================"

# 检查是否已有bot进程在运行
BOT_PID=$(ps aux | grep "main_bot.py" | grep -v grep | awk '{print $2}')

if [ -n "$BOT_PID" ]; then
    echo "⚠️  发现Bot进程正在运行 (PID: $BOT_PID)"
    echo "   正在停止旧进程..."
    kill $BOT_PID 2>/dev/null
    sleep 2
    
    # 如果还在运行，强制停止
    if ps -p $BOT_PID > /dev/null 2>&1; then
        echo "   强制停止进程..."
        kill -9 $BOT_PID 2>/dev/null
        sleep 1
    fi
    echo "✅ 旧进程已停止"
else
    echo "ℹ️  未发现运行中的Bot进程"
fi

# 备份日志
echo ""
echo "💾 备份日志..."
if [ -f "logs/bot.log" ]; then
    backup_file="logs/bot_$(date +%Y%m%d_%H%M%S).log"
    cp logs/bot.log "$backup_file"
    echo "✅ 日志已备份到: $backup_file"
fi

# 启动Bot（后台运行）
echo ""
echo "🚀 启动交易Bot..."

if [ ! -f "trading_bots/main_bot.py" ]; then
    echo "❌ 错误: 找不到文件 trading_bots/main_bot.py"
    echo "   当前目录: $(pwd)"
    echo "   目录文件:"
    ls -F
    exit 1
fi

echo "   注意: Bot会自动检测并监控现有持仓，不会影响现有订单"
export PYTHONPATH=$PYTHONPATH:$(pwd)
nohup python3 trading_bots/main_bot.py > logs/bot.log 2>&1 &
NEW_BOT_PID=$!

# 等待初始化
sleep 3

# 检查是否成功启动
if ps -p $NEW_BOT_PID > /dev/null 2>&1; then
    echo "✅ Bot已成功启动 (PID: $NEW_BOT_PID)"
    echo ""
    echo "📋 最新日志（最后10行）:"
    echo "========================================"
    tail -n 10 logs/bot.log
    echo ""
    echo "========================================"
    echo "✅ 重启完成！"
    echo ""
    echo "💡 提示:"
    echo "   - 查看实时日志: tail -f logs/bot.log"
    echo "   - 检查进程: ps aux | grep main_bot.py"
    echo "   - Bot会自动监控现有持仓，不会平仓或取消订单"
else
    echo "❌ Bot启动失败，请查看日志:"
    tail -n 20 logs/bot.log
    exit 1
fi


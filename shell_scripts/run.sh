#!/bin/bash

# ============================================
# Crypto DeepSeek 交易系统一键启动脚本
# ============================================

echo "🚀 正在启动 Crypto DeepSeek 交易系统..."
echo "========================================"

# 切换到项目目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR" || exit 1

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 未找到虚拟环境目录 venv"
    echo "请先运行部署脚本: ./deploy.sh"
    exit 1
fi

echo "✓ 找到虚拟环境: venv"

# 激活虚拟环境
source venv/bin/activate

# 检查依赖
echo ""
echo "📦 检查依赖包..."
if ! python3 -c "import ccxt, openai, flask, pandas" 2>/dev/null; then
    echo "❌ 缺少依赖包，请先运行: ./deploy.sh"
    exit 1
fi

echo "✓ 依赖包检查通过"

# 检查.env配置文件
echo ""
echo "🔐 检查配置文件..."
if [ ! -f .env ]; then
    echo "❌ 未找到 .env 配置文件"
    echo "请复制配置模板并填写你的API密钥:"
    echo "   cp .env.example .env"
    echo "   nano .env"
    exit 1
fi

# 验证必要的环境变量
if ! grep -q "DEEPSEEK_API_KEY=sk-" .env || ! grep -q "OKX_API_KEY=" .env; then
    echo "⚠️  警告: .env 文件中的API密钥可能未配置"
    echo "请确保已正确配置以下内容:"
    echo "  - DEEPSEEK_API_KEY"
    echo "  - OKX_API_KEY"
    echo "  - OKX_SECRET"
    echo "  - OKX_PASSWORD"
    read -p "是否继续启动? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "✓ 配置文件检查完成"

# 创建必要的目录
mkdir -p data logs

# 停止旧进程
echo ""
echo "🔄 检查并停止旧进程..."
pkill -f "main_bot.py" 2>/dev/null && echo "✓ 已停止旧的交易机器人进程"
pkill -f "deepseek_trading_bot.py" 2>/dev/null && echo "✓ 已停止旧的交易机器人进程"
pkill -f "trading_dashboard.py" 2>/dev/null && echo "✓ 已停止旧的仪表板进程"

# 启动交易机器人（后台运行）
echo ""
echo "🤖 启动交易机器人..."
export PYTHONPATH=$PYTHONPATH:.
nohup python3 trading_bots/main_bot.py > logs/bot.log 2>&1 &
BOT_PID=$!
echo "✓ 交易机器人已启动 (PID: $BOT_PID)"
echo "  日志文件: logs/bot.log"

# 等待机器人初始化
sleep 3

# 检查机器人是否正常运行
if ! ps -p $BOT_PID > /dev/null; then
    echo "❌ 交易机器人启动失败，请查看日志: logs/bot.log"
    echo "最近日志内容:"
    tail -n 10 logs/bot.log
    exit 1
fi

# 启动交易仪表板（前台运行）
echo ""
python3 trading_dashboard.py
echo "📊 启动交易仪表板..."
echo "========================================"
echo ""
echo "✅ 系统启动成功！"
echo ""
echo "📍 访问地址:"
echo "   本地: http://localhost:5000"
echo "   外网: http://$(curl -s ifconfig.me 2>/dev/null || echo 'your-server-ip'):5000"
echo ""
echo "📂 日志文件:"
echo "   交易机器人: logs/bot.log"
echo "   仪表板: 当前终端"
echo ""
echo "🔧 管理命令:"
echo "   查看机器人日志: tail -f logs/bot.log"
echo "   重启机器人: pkill -f main_bot.py && ./run.sh"
echo ""
echo "⚠️  按 Ctrl+C 停止服务"
echo "========================================"
echo ""

# 设置信号处理，确保退出时停止机器人
cleanup() {
    echo ""
    echo "🛑 正在停止交易机器人..."
    kill $BOT_PID 2>/dev/null
    sleep 2
    # 强制杀死如果还在运行
    kill -9 $BOT_PID 2>/dev/null
    echo "✓ 系统已完全停止"
    exit 0
}

# 捕获 Ctrl+C 信号
trap cleanup SIGINT SIGTERM

# 启动仪表板
python trading_dashboard.py

# 如果仪表板退出，停止机器人
cleanup


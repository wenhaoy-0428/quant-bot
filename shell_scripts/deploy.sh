#!/bin/bash

# ============================================
# Headache Trade V2 交易系统一键部署脚本
# ============================================

echo "🚀 Headache Trade V2 交易系统 - 一键部署"
echo "========================================"

# 检查是否在正确的目录
if [ ! -f "requirements.txt" ]; then
    echo "❌ 错误: 请在项目根目录运行此脚本"
    echo "   当前目录: $(pwd)"
    echo "   请切换到包含 requirements.txt 的目录"
    exit 1
fi

PROJECT_DIR=$(pwd)
echo "✓ 项目目录: $PROJECT_DIR"

# 检查 Python3 是否安装
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 Python3"
    echo "   请先安装 Python3: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

echo "✓ Python3 版本: $(python3 --version)"

# 清理旧的虚拟环境和缓存
echo ""
echo "🧹 清理旧的虚拟环境和缓存..."
if [ -d "myenv" ]; then
    echo "   删除 myenv 目录..."
    rm -rf myenv
fi

if [ -d "venv" ]; then
    echo "   删除 venv 目录..."
    rm -rf venv
fi

# 清理Python缓存
echo "   清理Python缓存..."
find . -type d -name "__pycache__" -not -path "./venv/*" -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -not -path "./venv/*" -delete 2>/dev/null || true

echo "✓ 旧虚拟环境和缓存已清理"

# 创建新的虚拟环境
echo ""
echo "📦 创建新的虚拟环境..."
python3 -m venv venv

if [ $? -ne 0 ]; then
    echo "❌ 创建虚拟环境失败"
    exit 1
fi

echo "✓ 虚拟环境创建成功"

# 激活虚拟环境
echo ""
echo "🔧 激活虚拟环境并安装依赖..."
source venv/bin/activate

# 升级 pip
echo "   升级 pip..."
pip install --upgrade pip -q

# 安装依赖
echo "   安装项目依赖..."
if ! pip install -r requirements.txt; then
    echo "❌ 依赖安装失败"
    echo "   请检查 requirements.txt 文件"
    echo "   尝试手动安装: pip install -r requirements.txt"
    exit 1
fi

echo "✓ 依赖安装完成"

# 创建必要的目录
echo ""
echo "📁 创建必要的目录..."
mkdir -p data logs static/css static/js templates scripts

# 确保脚本有执行权限
if [ -f "run.sh" ]; then
    chmod +x run.sh
fi
if [ -f "restart_bot_safe.sh" ]; then
    chmod +x restart_bot_safe.sh
fi
if [ -f "scripts/check_status.sh" ]; then
    chmod +x scripts/check_status.sh
fi
if [ -f "scripts/analyze_backtest_results.py" ]; then
    chmod +x scripts/analyze_backtest_results.py
fi
if [ -f "scripts/apply_config.py" ]; then
    chmod +x scripts/apply_config.py
fi

echo "✓ 目录创建完成，脚本权限已设置"

# 检查 .env 文件
echo ""
echo "🔐 检查环境配置文件..."
if [ ! -f ".env" ]; then
    echo "⚠️  未找到 .env 配置文件"
    
    # 检查是否有 .env.example 模板
    if [ -f ".env.example" ]; then
        echo "   从模板创建 .env 文件..."
        cp .env.example .env
        echo "✓ 已从 .env.example 创建 .env 文件"
        echo ""
        echo "📋 请编辑配置文件并填写你的 API 密钥:"
        echo "   nano .env"
    echo ""
        echo "   需要配置的密钥:"
    echo "      - DEEPSEEK_API_KEY (从 https://platform.deepseek.com/ 获取)"
    echo "      - OKX_API_KEY (从 https://www.okx.com/account/my-api 获取)"
    echo "      - OKX_SECRET"
    echo "      - OKX_PASSWORD"
        echo "      - CRYPTORACLE_API_KEY (可选)"
    echo ""
    echo "💡 配置完成后，运行 ./run.sh 启动系统"
    else
        echo "❌ 未找到 .env.example 模板文件"
        echo "   请手动创建 .env 文件并配置 API 密钥"
        exit 1
    fi
else
    echo "✓ 找到 .env 配置文件"
    
    # 简单验证配置
    if grep -q "DEEPSEEK_API_KEY=sk-" .env && grep -q "OKX_API_KEY=" .env; then
        echo "✓ API 密钥配置检查通过"
    else
        echo "⚠️  警告: .env 文件中的 API 密钥可能未正确配置"
        echo "   请确保已填写所有必需的 API 密钥"
    fi
fi

# 验证安装
echo ""
echo "🔍 验证安装..."
python -c "
import sys
missing_packages = []
try:
    import ccxt
except ImportError:
    missing_packages.append('ccxt')
try:
    import openai
except ImportError:
    missing_packages.append('openai')
try:
    import flask
except ImportError:
    missing_packages.append('flask')
try:
    import pandas
except ImportError:
    missing_packages.append('pandas')
try:
    import schedule
except ImportError:
    missing_packages.append('schedule')
try:
    import numpy
except ImportError:
    missing_packages.append('numpy')

if missing_packages:
    print('❌ 缺少依赖包: ' + ', '.join(missing_packages))
    sys.exit(1)
else:
    print('✓ 所有依赖包导入成功')
" 2>&1

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 部署完成！"
    echo "========================================"
    echo ""
    
    # 检查是否需要配置API密钥
    if [ -f ".env" ] && grep -q "DEEPSEEK_API_KEY=sk-" .env && grep -q "OKX_API_KEY=" .env && ! grep -q "your-.*-here" .env; then
        echo "✅ 系统已就绪，可以启动！"
        echo ""
        echo "📋 启动系统:"
        echo "   ./run.sh"
    else
    echo "📋 下一步操作:"
    echo "   1. 配置 API 密钥: nano .env"
    echo "   2. 启动系统: ./run.sh"
    fi
    
    echo ""
    echo "🌐 启动后访问地址:"
    echo "   本地: http://localhost:5000"
    SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "your-server-ip")
    echo "   外网: http://${SERVER_IP}:5000"
    echo ""
    echo "📚 更多信息请查看 README.md"
    echo ""
    echo "🔧 管理命令:"
    echo "   - 启动系统: ./run.sh"
    echo "   - 安全重启: ./restart_safe.sh"
    echo "   - 查看日志: tail -f logs/bot.log"
    echo "   - 检查状态: ./scripts/check_status.sh"
else
    echo "❌ 部署验证失败"
    echo "   请检查错误信息并重新运行部署脚本"
    exit 1
fi


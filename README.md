# Headache Trade V2.0 - 智能交易系统

Headache Trade V2.0 是一个基于 DeepSeek AI 的高级加密货币自动化交易系统。本项目采用"趋势为王，结构修边"的核心交易理念，结合量化分析与大模型决策，提供全自动的实盘交易、策略回测及可视化的监控仪表板。

## ✨ V2.0 核心特性

- 🤖 **DeepSeek AI 驱动** - 集成 DeepSeek 大模型，进行深度市场情绪与趋势分析。
- 📊 **"趋势为王" 策略引擎** - 多因子量化模型（均线系统、MACD、RSI、布林带）实时计算趋势强度。
- 🎯 **智能动态仓位** - 基于 AI 信心指数与市场波动率（ATR）动态调整杠杆与持仓比例。
- 🛡️ **三级风控体系** - 硬性止损、动态追踪止盈、ATR 波动保护机制。
- 📈 **实时可视化终端** - 全新的 Web 仪表板，提供账户概览、实时日志、收益曲线及持仓监控。
- ⚡ **自动化流水线** - 标准化 15 分钟交易周期，自动化的数据获取、清洗、分析与下单执行。

## 更新日志

### V2.0 (2026-01-13)
- 🚀 **全新AI优化引擎**: 集成DeepSeek AI进行策略参数优化，通过多轮迭代回测提升胜率和盈亏比。
- 📊 **策略管理工具**: 新增回测分析脚本 `analyze_backtest_results.py` 和自动配置工具 `apply_config.py`，实现从回测到实盘的闭环。
- 🛡️ **动态参数支持**: 实盘机器人支持从 `.env` 加载回测优化后的动态止盈止损和趋势强度参数。
- 📉 **风险看板**: 新增 `data/backtest_summary.csv` 自动汇总所有优化轨迹，直观对比策略表现。
- 🎯 **实战配置**: 预设经过迭代验证的 `opt_iter25` 配置（90% 极高胜率策略）。

### V1.0 (初始版本)
- 基础交易策略实现
- 简单风控机制
- 基本Web界面

## 📚 项目文档

为了帮助您更好地理解和使用本项目，我们提供了详细的文档：

- 📖 **[用户使用手册](docs/USER_GUIDE.md)** - 从环境搭建到高阶使用的完整指南（包含命令行操作）。
- 🚀 **[自动部署指南 (CI/CD)](DEPLOYMENT.md)** - 详细说明如何配置 GitHub Actions 实现全自动部署。
- ⚙️ **[交易参数详解](docs/TRADING_PARAMETERS.md)** - 深入了解策略背后的各项参数设置。

## 🚀 快速开始

### 1. 环境准备
确保您的系统已安装 Python 3.8+ 及 Git。

```bash
git clone <repository_url>
cd Headache_trade-1
```

### 2. 一键部署
运行部署脚本初始化环境及依赖：
```bash
./deploy.sh
```

### 3. 配置 API
复制环境配置模板并填入您的 API 密钥：
```bash
cp .env.example .env
nano .env
```
*必需配置项：*
- `AI_API_KEY`: AI 模型接口密钥（支持 DeepSeek, OpenAI 等）
- `AI_BASE_URL`: AI API 基础 URL
- `MODEL_NAME`: 使用的模型名称
- `OKX_API_KEY`, `OKX_SECRET`, `OKX_PASSWORD`: OKX 交易所 V5 API

### 4. 启动系统
```bash
./run.sh
```
启动成功后：
- 🤖 **交易机器人**将在后台运行 (PID 记录于 `logs/bot.log`)
- 📊 **Web 仪表板**将启动在前台，访问地址：`http://localhost:5000`

## 📁 项目结构 (V2.0)

```text
Headache_trade-1/
├── run.sh                        # [入口] 系统一键启动脚本
├── deploy.sh                     # [入口] 环境部署脚本
├── restart_bot_safe.sh           # [工具] 安全重启脚本（保护现有持仓）
├── trading_dashboard.py          # [核心] Web 可视化监控服务
├── trading_bots/                 # [核心] 交易策略模块
│   ├── main_bot.py               # >>> V2.0 主策咯引擎 (原 deepseek_Fluc_reduce_version)
│   ├── risk.py                   # 风控模块
│   └── execution.py              # 订单执行模块
├── docs/                         # [文档] 项目文档与优化记录
│   ├── OPTIMIZATION_SUCCESS.md   # 优化成果记录
│   └── TRADING_PARAMETERS.md     # 交易参数说明
├── scripts/                      # [工具] 分析与回测工具
│   ├── analyze_backtest_results.py # 自动分析回测数据并汇总结果报告
│   ├── apply_config.py           # 一键应用最佳回测参数至实盘配置文件 (.env)
│   └── check_status.sh           # 进程状态检测
├── templates/                    # [前端] Web 页面模板
├── static/                       # [前端] 静态资源
├── data/                         # [数据] 本地数据存储
├── logs/                         # [日志] 运行日志目录
└── venv/                         # Python 虚拟环境
```

## 🛠️ 运维管理

### 推荐操作
- **查看实时日志**:
  ```bash
  tail -f logs/bot.log
  ```
- **安全重启 (推荐)**:
  *并在重启前自动备份日志，且不会影响已有持仓*
  ```bash
  ./restart_bot_safe.sh
  ```

### 进程控制
- **手动停止**:
  ```bash
  # 停止交易机器人
  pkill -f main_bot.py
  
  # 停止 Web 仪表板
  pkill -f trading_dashboard.py
  ```

## 🎯 策略详情

### 趋势判断标准
系统基于 15 分钟 K 线数据，结合以下指标计算趋势评分 (0-10):
1.  **MA 均线系统**: 多周期排列 (MA7, MA25, MA99)
2.  **MACD**: 零轴位置与金叉/死叉状态
3.  **RSI**: 相对强弱与背离检测
4.  **布林带**: 价格相对位置与开口方向

### 资金管理
- **基础仓位**: 默认 10% 账户权益
- **杠杆倍数**: 3x - 10x (动态调整)
- **调整逻辑**: AI 信心分 > 8 且趋势分 > 7 时触发加仓；ATR 剧烈波动时自动降维。

## 🔒用于生产环境的安全建议
1.  **Key 权限**: OKX API Key 务必仅开启 **"交易"** 与 **"读取"** 权限，**严禁开启"提币"权限**。
2.  **IP 白名单**: 建议将 API Key 绑定服务器 IP。
3.  **日志监控**: 定期检查 `logs/bot.log` 确保运行正常。

## 📄 License & 免责声明
本项目基于 MIT License 开源。
**风险提示**: 加密货币交易具有极高风险，本系统提供的策略与代码仅供参考与学习，作者不对任何交易损失负责。

---
**Headache Trade** - *Let AI handle the headache of trading.*

# Copilot Instructions — Headache Trade V2.1

## Architecture Overview

This is a **dual-process automated crypto trading system** targeting OKX perpetual futures, driven by DeepSeek AI.

### Two Processes
1. **Trading Bot** (`trading_bots/main_bot.py`) — the "soldier": fast 15-minute candle loop. Reads market data, computes technical indicators, calls DeepSeek for a signal, and executes orders on OKX via `ccxt`.
2. **Flask API Server** (`trading_dashboard.py`) — serves the web dashboard and exposes REST endpoints that the Next.js frontend consumes.

### Commander / Soldier Pattern
`ai_commander.py` runs as a *separate slow process* that calls DeepSeek for macro guidance and writes `data/guidance.json`. `main_bot.py` reads this file on each cycle — this decouples slow AI calls from the fast trading loop. Never block the soldier loop on an async AI call.

### Frontend
`frontend_dashboard/` is a **Next.js 15 + TypeScript + Tailwind CSS** app. It calls the Flask backend via relative `/api/*` routes (proxied through Next.js). Data-fetching uses `@tanstack/react-query`. Charts use **ECharts** (`echarts-for-react`). All API interactions are in `frontend_dashboard/lib/api.ts`, which also normalizes raw backend data into typed shapes.

### Data Flow
```
OKX Exchange ──► main_bot.py ──► data/dashboard_data.json ──► trading_dashboard.py (Flask) ──► Next.js frontend
DeepSeek API ──► ai_commander.py ──► data/guidance.json ──► main_bot.py
```

## Key Python Modules

| File | Responsibility |
|------|---------------|
| `trading_bots/config.py` | Central config: instantiates `exchange` (ccxt OKX), `deepseek_client` (OpenAI SDK pointed at DeepSeek), `TRADE_CONFIG`, `performance_tracker`, `signal_history` |
| `trading_bots/main_bot.py` | Main loop: fetches OHLCV, calls signals, manages `PriceMonitor`, writes dashboard data |
| `trading_bots/signals.py` | Signal generation: `generate_trend_king_signal`, `analyze_with_deepseek_trend_king_with_retry`, `get_sentiment_indicators` |
| `trading_bots/indicators.py` | Pure technical analysis: MA, MACD, RSI, Bollinger, ATR, `detect_market_regime` |
| `trading_bots/execution.py` | OKX order placement: `get_current_position`, `set_tp_sl_orders`, `cancel_tp_sl_orders` |
| `trading_bots/risk.py` | Position sizing, drawdown checks |
| `trading_bots/guidance.py` | `load_guidance` / `save_guidance` for the commander/soldier JSON handoff |

## Commands

### Python Backend
```bash
# First-time setup
./deploy.sh

# Start trading bot only
./run.sh

# Start both Flask API + Next.js frontend
./start_services.sh
# Backend: http://localhost:5001
# Frontend: http://localhost:3000

# Safe restart (preserves open positions)
./restart_bot_safe.sh

# Run Python files manually (always set PYTHONPATH)
PYTHONPATH=. python3 trading_bots/main_bot.py
PYTHONPATH=. python3 trading_dashboard.py

# Install dependencies
pip install -r requirements.txt
```

### Frontend
```bash
cd frontend_dashboard
npm install
npm run dev      # dev server on :3000
npm run build    # production build
npm run lint     # ESLint check
```

### Logs
```bash
tail -f logs/bot.log          # trading bot
tail -f logs/dashboard.log    # Flask API
tail -f logs/commander.log    # AI commander
```

## Environment Variables

Copy `.env.example` to `.env`. Required keys:

| Variable | Purpose |
|----------|---------|
| `DEEPSEEK_API_KEY` | DeepSeek API (also accepted as `OPENAI_API_KEY`) |
| `OKX_API_KEY` | OKX exchange key |
| `OKX_SECRET` / `OKX_SECRET_KEY` | OKX secret (both aliases accepted) |
| `OKX_PASSWORD` / `OKX_PASSPHRASE` | OKX API passphrase (both aliases accepted) |
| `OKX_SANDBOX` | Set `true` for paper trading |
| `BOT_SYMBOL` | Trading pair, default `BTC/USDT:USDT` |
| `BOT_TIMEFRAME` | Candle interval, default `15m` |
| `BOT_LEVERAGE` | Default `6` |

All `TRADE_CONFIG` fields are also overridable via `.env` (e.g. `BOT_TEST_MODE`, `BOT_CONTRACT_SIZE`).

## Key Conventions

- **PYTHONPATH must be `.`** when running any file from the project root, because all imports use `from trading_bots.xxx import ...`.
- **`config.py` is the single source of truth** for all shared state (`exchange`, `deepseek_client`, `TRADE_CONFIG`, `performance_tracker`, `signal_history`). Never instantiate a new `ccxt.okx` or `OpenAI` client in other modules — import from `config`.
- **File-based IPC**: The bot and dashboard communicate via JSON files in `data/` (not sockets or a database). Always use `fcntl.flock` for shared reads/writes to avoid corruption.
- **DeepSeek is called via OpenAI SDK**: The client in `config.py` points `base_url` to `https://api.deepseek.com`. Use the same client for all LLM calls.
- **Frontend API normalization**: Raw backend responses often have inconsistent field names. Always add normalization helpers in `lib/api.ts` (e.g. `normalizePositions`, `normalizeTrades`) rather than handling it in components.
- **Fallback data in frontend**: All `api.*` functions in `lib/api.ts` catch errors and return fallback/mock data rather than throwing — components should always render even if the backend is down.
- **Trailing stop / orbit protection**: The bot uses a multi-level "orbit" protection system with `PROTECTION_LEVELS` (defensive/balanced/aggressive). Time-based activation is controlled by `ORBIT_INITIAL_PROTECTION_TIME` and `ORBIT_MIN_TRIGGER_TIME` constants in `config.py`.
- **Backtest → live pipeline**: `scripts/backtest_engine.py` runs backtests; `scripts/apply_config.py` writes optimized params back to `.env`. Results aggregate into `data/backtest_summary.csv`.

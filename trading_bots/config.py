import os
from datetime import datetime
from dotenv import load_dotenv
import ccxt
from openai import OpenAI

# Load environment variables early
load_dotenv()

# ---------------------------------------------------------------------------
# API clients
# ---------------------------------------------------------------------------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")

# Instantiate DeepSeek client (safe even if key is missing; calls will fail loudly)
deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

# OKX exchange setup (public endpoints still work without keys)
OKX_API_KEY = os.getenv("OKX_API_KEY", "")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY") or os.getenv("OKX_SECRET") or ""
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE") or os.getenv("OKX_PASSWORD") or ""
IS_SANDBOX = os.getenv("OKX_SANDBOX", "false").lower() == "true"

exchange = ccxt.okx({
    "apiKey": OKX_API_KEY,
    "secret": OKX_SECRET_KEY,
    "password": OKX_PASSPHRASE,
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",
    },
})

# Enable sandbox if requested
try:
    exchange.set_sandbox_mode(IS_SANDBOX)
except Exception:
    # If sandbox toggle fails, continue in live/public mode
    pass

# ---------------------------------------------------------------------------
# Trading and risk constants
# ---------------------------------------------------------------------------
TRADING_FEE_RATE = 0.001  # 0.10% total buffer for quick PnL math

LOCK_STOP_LOSS_PROFIT_THRESHOLD = 2.0  # % profit to arm lock-stop
LOCK_STOP_LOSS_BUFFER = 0.1  # % buffer above breakeven when arming lock-stop
LOCK_STOP_LOSS_RATIO = 0.3  # default 30% lock ratio
LOCK_STOP_LOSS_RATIOS = {
    "low": {"min_profit": 0.0, "max_profit": 0.02, "ratio": 0.30},
    "medium": {"min_profit": 0.02, "max_profit": 0.05, "ratio": 0.45},
    "high": {"min_profit": 0.05, "max_profit": 1.00, "ratio": 0.60},
}

ORBIT_UPDATE_INTERVAL = 300  # seconds between protection orbit syncs
ORBIT_INITIAL_PROTECTION_TIME = 300  # seconds after entry before orbit updates
ORBIT_MIN_TRIGGER_TIME = 180  # seconds after entry before orbit can trigger exits
POSITION_VERIFY_PROTECTION_SECONDS = 60  # grace period to avoid early clear
POSITION_VERIFY_FAIL_THRESHOLD = 3  # retries before clearing ghost position

PROTECTION_LEVELS = {
    "defensive": {
        "activation_time": 30,
        "take_profit_multiplier": 0.8,
        "stop_loss_multiplier": 1.8,
    },
    "balanced": {
        "activation_time": 60,
        "take_profit_multiplier": 1.2,
        "stop_loss_multiplier": 1.2,
        "min_profit_required": 0.002,  # 0.2%
    },
    "aggressive": {
        "activation_time": 120,
        "take_profit_multiplier": 1.8,
        "stop_loss_multiplier": 0.8,
        "min_profit_required": 0.005,  # 0.5%
    },
}

TRADE_CONFIG = {
    "symbol": os.getenv("BOT_SYMBOL", "BTC/USDT:USDT"),
    "timeframe": os.getenv("BOT_TIMEFRAME", "15m"),
    "data_points": int(os.getenv("BOT_DATA_POINTS", "200")),
    "leverage": int(os.getenv("BOT_LEVERAGE", "6")),
    "test_mode": os.getenv("BOT_TEST_MODE", "false").lower() == "true",
    "force_min_position": False,
    "contract_size": float(os.getenv("BOT_CONTRACT_SIZE", "0.01")),
    "min_amount": float(os.getenv("BOT_MIN_AMOUNT", "0.01")),
    "performance_tracking": {
        "daily_pnl_threshold": float(os.getenv("BOT_DAILY_PNL_THRESHOLD", "-0.05")),
    },
    "risk_management": {
        "base_risk_per_trade": float(os.getenv("BOT_BASE_RISK_PER_TRADE", "0.02")),
        "adaptive_risk_enabled": os.getenv("BOT_ADAPTIVE_RISK", "true").lower() == "true",
        "min_trades_for_adaptive": int(os.getenv("BOT_MIN_TRADES_ADAPTIVE", "10")),
        "risk_levels": {
            "high_win_rate": {"threshold": 0.60, "min_risk": 0.05, "max_risk": 0.10},
            "medium_win_rate": {"threshold": 0.40, "min_risk": 0.03, "max_risk": 0.05},
            "low_win_rate": {"threshold": 0.00, "min_risk": 0.01, "max_risk": 0.02},
        },
        "max_position_drawdown": float(os.getenv("BOT_MAX_POSITION_DRAWDOWN", "0.03")),
        "target_capital_utilization": float(os.getenv("BOT_TARGET_UTIL", "0.50")),
        "max_capital_utilization": float(os.getenv("BOT_MAX_UTIL", "0.60")),
        "min_capital_utilization": float(os.getenv("BOT_MIN_UTIL", "0.30")),
        "min_leverage": int(os.getenv("BOT_MIN_LEVERAGE", "1")),
        "max_leverage": int(os.getenv("BOT_MAX_LEVERAGE", "10")),
    },
}

performance_tracker = {
    "trade_count": 0,
    "win_count": 0,
    "loss_count": 0,
    "win_rate": 0.0,
    "trade_results": [],
    "daily_pnl": 0.0,
    "daily_trade_count": 0,
    "last_trade_time": None,
    "last_trade_date": None,
    "is_trading_paused": False,
}

signal_history = []

__all__ = [
    "deepseek_client",
    "exchange",
    "TRADE_CONFIG",
    "TRADING_FEE_RATE",
    "LOCK_STOP_LOSS_PROFIT_THRESHOLD",
    "LOCK_STOP_LOSS_BUFFER",
    "LOCK_STOP_LOSS_RATIO",
    "LOCK_STOP_LOSS_RATIOS",
    "ORBIT_UPDATE_INTERVAL",
    "ORBIT_INITIAL_PROTECTION_TIME",
    "ORBIT_MIN_TRIGGER_TIME",
    "POSITION_VERIFY_PROTECTION_SECONDS",
    "POSITION_VERIFY_FAIL_THRESHOLD",
    "PROTECTION_LEVELS",
    "performance_tracker",
    "signal_history",
]

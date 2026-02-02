"""
Configuration loader for the trading bot.
Loads settings from environment variables with sensible defaults.
"""

import os
from typing import Any, Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Central configuration management."""
    
    def __init__(self):
        """Initialize configuration from environment variables."""
        # API Configuration
        self.ai_api_key = self._get_required_env("AI_API_KEY", fallbacks=["DEEPSEEK_API_KEY", "OPENAI_API_KEY"])
        self.ai_base_url = self._get_required_env("AI_BASE_URL", fallbacks=["DEEPSEEK_BASE_URL"], default="https://api.deepseek.com")
        self.model_name = self._get_required_env("MODEL_NAME", default="deepseek-chat")
        
        # Exchange Configuration
        self.exchange_api_key = self._get_required_env("EXCHANGE_API_KEY")
        self.exchange_secret_key = self._get_required_env("EXCHANGE_SECRET", fallbacks=["EXCHANGE_SECRET_KEY"])
        self.exchange_passphrase = self._get_required_env("EXCHANGE_PASSPHRASE")
        self.exchange_enable_sandbox = os.getenv("EXCHANGE_ENABLE_SANDBOX", "false").lower() == "true"
        
        # Trading Configuration
        self.symbol = os.getenv("BOT_SYMBOL", "BTC/USDT:USDT")
        self.timeframe = os.getenv("BOT_TIMEFRAME", "15m")
        self.data_points = int(os.getenv("BOT_DATA_POINTS", "200"))
        self.leverage = int(os.getenv("BOT_LEVERAGE", "6"))
        self.test_mode = os.getenv("BOT_TEST_MODE", "false").lower() == "true"
        self.contract_size = float(os.getenv("BOT_CONTRACT_SIZE", "0.01"))
        self.min_amount = float(os.getenv("BOT_MIN_AMOUNT", "0.01"))
        
        # Risk Management Configuration
        self.base_risk_per_trade = float(os.getenv("BOT_BASE_RISK_PER_TRADE", "0.02"))
        self.adaptive_risk_enabled = os.getenv("BOT_ADAPTIVE_RISK", "true").lower() == "true"
        self.min_trades_for_adaptive = int(os.getenv("BOT_MIN_TRADES_ADAPTIVE", "10"))
        self.max_position_drawdown = float(os.getenv("BOT_MAX_POSITION_DRAWDOWN", "0.03"))
        self.target_capital_utilization = float(os.getenv("BOT_TARGET_UTIL", "0.50"))
        self.max_capital_utilization = float(os.getenv("BOT_MAX_UTIL", "0.60"))
        self.min_capital_utilization = float(os.getenv("BOT_MIN_UTIL", "0.30"))
        self.min_leverage = int(os.getenv("BOT_MIN_LEVERAGE", "1"))
        self.max_leverage = int(os.getenv("BOT_MAX_LEVERAGE", "10"))
        
        # Performance Tracking
        self.daily_pnl_threshold = float(os.getenv("BOT_DAILY_PNL_THRESHOLD", "-0.05"))
        
        # Trading Fee
        self.trading_fee_rate = 0.001  # 0.10% total buffer
        
    def _get_required_env(self, key: str, fallbacks: list = None, default: str = None) -> str:
        """Get required environment variable with optional fallbacks.
        
        Args:
            key: Primary environment variable name
            fallbacks: List of fallback variable names to try
            default: Default value if provided (makes it optional)
            
        Returns:
            The environment variable value
            
        Raises:
            ValueError: If the required variable is not set and no default provided
        """
        value = os.getenv(key)
        
        if not value and fallbacks:
            for fallback in fallbacks:
                value = os.getenv(fallback)
                if value:
                    break
        
        if not value:
            if default is not None:
                return default
            raise ValueError(
                f"Required environment variable '{key}' is not set. "
                f"Please set it in your .env file."
            )
        
        return value
    
    def get_risk_levels(self) -> Dict[str, Dict[str, float]]:
        """Get risk levels configuration."""
        return {
            "high_win_rate": {
                "threshold": 0.60,
                "min_risk": 0.05,
                "max_risk": 0.10
            },
            "medium_win_rate": {
                "threshold": 0.40,
                "min_risk": 0.03,
                "max_risk": 0.05
            },
            "low_win_rate": {
                "threshold": 0.00,
                "min_risk": 0.01,
                "max_risk": 0.02
            }
        }
    
    def get_protection_levels(self) -> Dict[str, Dict[str, Any]]:
        """Get protection levels configuration."""
        return {
            "defensive": {
                "activation_time": 30,
                "take_profit_multiplier": 0.8,
                "stop_loss_multiplier": 1.8,
            },
            "balanced": {
                "activation_time": 60,
                "take_profit_multiplier": 1.2,
                "stop_loss_multiplier": 1.2,
                "min_profit_required": 0.002,
            },
            "aggressive": {
                "activation_time": 120,
                "take_profit_multiplier": 1.8,
                "stop_loss_multiplier": 0.8,
                "min_profit_required": 0.005,
            },
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary format (legacy compatibility)."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "data_points": self.data_points,
            "leverage": self.leverage,
            "test_mode": self.test_mode,
            "force_min_position": False,
            "contract_size": self.contract_size,
            "min_amount": self.min_amount,
            "performance_tracking": {
                "daily_pnl_threshold": self.daily_pnl_threshold,
            },
            "risk_management": {
                "base_risk_per_trade": self.base_risk_per_trade,
                "adaptive_risk_enabled": self.adaptive_risk_enabled,
                "min_trades_for_adaptive": self.min_trades_for_adaptive,
                "risk_levels": self.get_risk_levels(),
                "max_position_drawdown": self.max_position_drawdown,
                "target_capital_utilization": self.target_capital_utilization,
                "max_capital_utilization": self.max_capital_utilization,
                "min_capital_utilization": self.min_capital_utilization,
                "min_leverage": self.min_leverage,
                "max_leverage": self.max_leverage,
            },
        }


# Singleton instance
config = Config()


__all__ = ["Config", "config"]

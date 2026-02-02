"""
Exchange Service - Handles all exchange interactions.

This service provides a unified interface for interacting with cryptocurrency exchanges,
specifically optimized for OKX. It follows the Singleton pattern to ensure only one
exchange connection exists throughout the application lifecycle.

Key Features:
- Singleton pattern for efficient connection management
- Automatic market loading on initialization
- Comprehensive market data fetching (OHLCV, tickers, funding rates)
- Position management and monitoring
- Order execution (market, limit, conditional)
- Take-profit and stop-loss order management
- Balance and trade history retrieval

Usage:
    from core.services.exchange_service import exchange_service
    
    # Markets are already loaded on import
    balance = exchange_service.fetch_balance()
    position = exchange_service.get_current_position()

---

交易所服务 - 处理所有交易所交互。

本服务提供了与加密货币交易所交互的统一接口，专门为 OKX 优化。
它遵循单例模式，确保整个应用程序生命周期中只存在一个交易所连接。

主要特性：
- 单例模式实现高效的连接管理
- 初始化时自动加载市场数据
- 全面的市场数据获取（OHLCV、行情、资金费率）
- 持仓管理和监控
- 订单执行（市价、限价、条件单）
- 止盈止损订单管理
- 余额和交易历史查询

使用方法：
    from core.services.exchange_service import exchange_service
    
    # 导入时市场数据已自动加载
    balance = exchange_service.fetch_balance()
    position = exchange_service.get_current_position()
"""

import time
import traceback
from typing import Dict, List, Optional, Tuple, Any
import ccxt
from datetime import datetime

from core.config import config


class ExchangeService:
    """
    Singleton service for cryptocurrency exchange interactions.
    
    This class manages all interactions with the exchange API, including market data,
    positions, orders, and account information. It uses the Singleton pattern to ensure
    only one instance exists, preventing multiple connections and ensuring consistent state.
    
    Attributes:
        exchange: CCXT exchange instance (OKX)
        _instance: Singleton instance reference
        _initialized: Flag to prevent re-initialization
    
    Thread Safety:
        This implementation is not thread-safe. If using in multi-threaded environments,
        external synchronization is required.

    ---

    加密货币交易所交互的单例服务。
    
    此类管理与交易所 API 的所有交互，包括市场数据、持仓、订单和账户信息。
    它使用单例模式确保只存在一个实例，防止多个连接并确保状态一致。
    
    属性：
        exchange: CCXT 交易所实例（OKX）
        _instance: 单例实例引用
        _initialized: 防止重复初始化的标志
    
    线程安全：
        此实现不是线程安全的。如果在多线程环境中使用，需要外部同步机制。
    """
    
    _instance: Optional['ExchangeService'] = None
    _initialized: bool = False
    
    def __new__(cls):
        """
        Ensure only one instance exists (Singleton pattern).
        
        Returns:
            The single ExchangeService instance

        ---

        确保只存在一个实例（单例模式）。
        
        返回：
            唯一的 ExchangeService 实例
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """
        Initialize exchange connection and load markets.
        
        This method is idempotent - it only performs initialization once,
        even if called multiple times. On first initialization:
        - Creates CCXT OKX exchange instance with API credentials
        - Configures sandbox mode if enabled
        - Loads all available markets from the exchange
        
        Raises:
            ValueError: If required API credentials are missing (via config)

        ---

        初始化交易所连接并加载市场数据。
        
        此方法是幂等的 - 即使多次调用也只执行一次初始化。首次初始化时：
        - 使用 API 凭证创建 CCXT OKX 交易所实例
        - 如果启用则配置沙盒模式
        - 从交易所加载所有可用市场
        
        异常：
            ValueError: 如果缺少必需的 API 凭证（通过 config）
        """
        # Skip initialization if already initialized
        if self._initialized:
            return
            
        # Create exchange instance with credentials from config
        self.exchange = ccxt.okx({
            "apiKey": config.exchange_api_key,
            "secret": config.exchange_secret_key,
            "password": config.exchange_passphrase,
            "enableRateLimit": True,  # Respect exchange rate limits
            "options": {
                "defaultType": "swap",  # Use perpetual futures by default
            },
        })
        
        # Enable sandbox mode if configured (for testing without real funds)
        try:
            self.exchange.set_sandbox_mode(config.exchange_enable_sandbox)
        except Exception:
            pass  # Continue in live/public mode if sandbox toggle fails
        
        # Load markets on initialization for immediate availability
        print("🔄 Loading exchange markets...")
        try :
            self.exchange.load_markets()
            print(f"✅ Loaded {len(self.exchange.markets)} markets")
        except Exception as e:
            print(f"❌ Failed to load markets during initialization: {e}")

        self._initialized = True
    
    def reload_markets(self) -> Dict[str, Any]:
        """
        Load and cache market information.
        
        Markets are automatically loaded during initialization, but this method
        can be called to reload market data if needed (e.g., after extended runtime).
        
        Returns:
            Dictionary of market information keyed by symbol

        ---

        加载并缓存市场信息。
        
        市场数据在初始化时自动加载，但如果需要可以调用此方法重新加载市场数据（例如，长时间运行后）。
        
        返回：
            以交易对为键的市场信息字典
        """

        try:
            print("🔄 Reloading exchange markets...")
            markets = self.exchange.load_markets(reload=True)
            print(f"✅ Reloaded {len(markets)} markets")
            return markets
        except Exception as e:
            print(f"❌ Failed to reload markets: {e}")
    
        return {}
    
    # ==================== Market Data Methods ====================
    
    def fetch_ohlcv(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[List]:
        """
        Fetch OHLCV (candlestick) data.
        
        Args:
            symbol: Trading pair symbol (default: from config)
            timeframe: Timeframe for candles (default: from config)
            limit: Number of candles to fetch (default: from config)
            
        Returns:
            List of OHLCV data [timestamp, open, high, low, close, volume]
        """
        symbol = symbol or config.symbol
        timeframe = timeframe or config.timeframe
        limit = limit or config.data_points
        
        return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    
    def fetch_ticker(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch current ticker data.
        
        Args:
            symbol: Trading pair symbol (default: from config)
            
        Returns:
            Dictionary with ticker information (last price, bid, ask, etc.)
        """
        symbol = symbol or config.symbol
        return self.exchange.fetch_ticker(symbol)
    
    def fetch_funding_rate(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch current funding rate for perpetual contracts.
        
        Args:
            symbol: Trading pair symbol (default: from config)
            
        Returns:
            Dictionary with funding rate information
        """
        symbol = symbol or config.symbol
        return self.exchange.fetch_funding_rate(symbol)
    
    def fetch_balance(self) -> Dict[str, Any]:
        """
        Fetch account balance.
        
        Returns:
            Dictionary with balance information for all currencies
        """
        return self.exchange.fetch_balance()
    
    def fetch_account_balance_usdt(self) -> Tuple[float, float]:
        """
        Fetch USDT balance with safe fallbacks.
        
        This method attempts to retrieve USDT balance with multiple fallback strategies
        to handle different exchange response formats. If fetching fails, returns a
        default value of 1000 USDT to prevent trading interruption.
        
        Returns:
            Tuple of (free_balance, total_balance) in USDT
            - free_balance: Available balance for new positions
            - total_balance: Total balance including positions
        
        Note:
            If both values are 0, checks nested 'info' field (exchange-specific)
            If only one value is available, uses it for both fields

        ---

        获取 USDT 余额，带安全降级策略。
        
        此方法尝试使用多种降级策略获取 USDT 余额，以处理不同的交易所响应格式。
        如果获取失败，返回默认值 1000 USDT 以防止交易中断。
        
        返回：
            (可用余额, 总余额) 的元组，单位为 USDT
            - free_balance: 可用于新仓位的余额
            - total_balance: 包括持仓在内的总余额
        
        注意：
            如果两个值都为 0，检查嵌套的 'info' 字段（交易所特定）
            如果只有一个值可用，则两个字段都使用它
        """
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get("USDT", {})
            total = float(usdt.get("total", 0) or 0)
            free = float(usdt.get("free", 0) or 0)
            
            # Some exchanges nest under 'info'
            if total == 0 and free == 0:
                total = float(balance.get("total", {}).get("USDT", 0) or 0)
                free = float(balance.get("free", {}).get("USDT", 0) or 0)
            
            if total == 0:
                total = free
            if free == 0:
                free = total
                
            return free, total
        except Exception as exc:
            print(f"⚠️ 获取账户余额失败，使用1000 USDT默认值: {exc}")
            return 1000.0, 1000.0
    
    # ==================== Position Management ====================
    
    def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Fetch current positions.
        
        Args:
            symbols: List of symbols to fetch positions for (default: [config.symbol])
            
        Returns:
            List of position dictionaries
        """
        if symbols is None:
            symbols = [config.symbol]
        return self.exchange.fetch_positions(symbols)
    
    def get_current_position(self, symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get current position for a symbol.
        
        Fetches and parses the current position, returning None if no position exists
        or if the position size is 0.
        
        Args:
            symbol: Trading pair symbol (default: from config)
            
        Returns:
            Position dictionary with keys:
                - side: 'long' or 'short'
                - size: Position size in contracts
                - entry_price: Average entry price
                - unrealized_pnl: Current unrealized profit/loss
                - leverage: Current leverage
                - symbol: Trading symbol
            Returns None if no position or on error
        
        Note:
            Only returns positions with contracts > 0

        ---

        获取指定交易对的当前持仓。
        
        获取并解析当前持仓，如果不存在持仓或持仓大小为 0 则返回 None。
        
        参数：
            symbol: 交易对符号（默认：从配置读取）
            
        返回：
            持仓信息字典，包含以下键：
                - side: 'long' 或 'short'
                - size: 持仓大小（合约数）
                - entry_price: 平均开仓价格
                - unrealized_pnl: 当前未实现盈亏
                - leverage: 当前杠杆
                - symbol: 交易符号
            如果无持仓或发生错误则返回 None
        
        注意：
            仅返回合约数 > 0 的持仓
        """
        symbol = symbol or config.symbol
        
        try:
            positions = self.fetch_positions([symbol])
            for pos in positions:
                if pos['symbol'] == symbol:
                    contracts = float(pos['contracts']) if pos['contracts'] else 0
                    if contracts > 0:
                        return {
                            'side': pos['side'],
                            'size': contracts,
                            'entry_price': float(pos['entryPrice']) if pos['entryPrice'] else 0,
                            'unrealized_pnl': float(pos['unrealizedPnl']) if pos['unrealizedPnl'] else 0,
                            'leverage': float(pos['leverage']) if pos['leverage'] else config.leverage,
                            'symbol': pos['symbol'],
                        }
            return None
        except Exception as e:
            print(f"获取持仓失败: {e}")
            traceback.print_exc()
            return None
    
    def set_leverage(self, leverage: int, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Set leverage for a symbol.
        
        Args:
            leverage: Leverage multiplier
            symbol: Trading pair symbol (default: from config)
            
        Returns:
            Response from exchange
        """
        symbol = symbol or config.symbol
        return self.exchange.set_leverage(leverage, symbol)
    
    # ==================== Order Execution ====================
    
    def create_market_order(
        self,
        side: str,
        amount: float,
        symbol: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a market order.
        
        Args:
            side: 'buy' or 'sell'
            amount: Order amount in contracts
            symbol: Trading pair symbol (default: from config)
            params: Additional parameters (e.g., {'reduceOnly': True})
            
        Returns:
            Order information dictionary
        """
        symbol = symbol or config.symbol
        params = params or {}
        return self.exchange.create_market_order(symbol, side, amount, params=params)
    
    def create_limit_order(
        self,
        side: str,
        amount: float,
        price: float,
        symbol: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a limit order.
        
        Args:
            side: 'buy' or 'sell'
            amount: Order amount in contracts
            price: Limit price
            symbol: Trading pair symbol (default: from config)
            params: Additional parameters
            
        Returns:
            Order information dictionary
        """
        symbol = symbol or config.symbol
        params = params or {}
        return self.exchange.create_limit_order(symbol, side, amount, price, params=params)
    
    # ==================== Conditional Orders (TP/SL) ====================
    
    def set_tp_sl_orders(
        self,
        position_side: str,
        position_size: float,
        stop_loss_price: float,
        take_profit_price: float,
        symbol: Optional[str] = None,
        entry_price: Optional[float] = None
    ) -> Optional[Dict[str, Optional[str]]]:
        """
        Set take-profit and stop-loss conditional orders (OKX specific).
        
        Creates conditional orders that will automatically close the position when
        the market reaches the specified trigger prices. Uses mark price triggers
        to avoid manipulation and market orders for execution (-1 price).
        
        Process:
        1. Cancels all existing TP/SL orders for the symbol
        2. Creates new stop-loss order (if price > 0)
        3. Creates new take-profit order (if price > 0)
        
        Args:
            position_side: 'long' or 'short' - determines order direction
            position_size: Position size in contracts to close
            stop_loss_price: Stop loss trigger price (0 to skip)
            take_profit_price: Take profit trigger price (0 to skip)
            symbol: Trading pair symbol (default: from config)
            entry_price: Entry price (optional, for reference only)
            
        Returns:
            Dictionary with order IDs: {'tp_order_id': str, 'sl_order_id': str}
            Returns None if both orders fail
            
        Note:
            - Uses mark price triggers to prevent price manipulation
            - Orders execute at market price (-1) when triggered
            - Automatically cancels old orders before setting new ones
            - Continues on partial failure (one order may succeed while other fails)

        ---

        设置止盈止损条件单（OKX 专用）。
        
        创建条件单，当市场达到指定触发价格时自动平仓。使用标记价格触发以避免操纵，
        使用市价单执行（-1 价格）。
        
        流程：
        1. 取消该交易对的所有现有止盈止损订单
        2. 创建新的止损订单（如果价格 > 0）
        3. 创建新的止盈订单（如果价格 > 0）
        
        参数：
            position_side: 'long' 或 'short' - 决定订单方向
            position_size: 要平仓的持仓大小（合约数）
            stop_loss_price: 止损触发价格（0 表示跳过）
            take_profit_price: 止盈触发价格（0 表示跳过）
            symbol: 交易对符号（默认：从配置读取）
            entry_price: 入场价格（可选，仅供参考）
            
        返回：
            包含订单 ID 的字典：{'tp_order_id': str, 'sl_order_id': str}
            如果两个订单都失败则返回 None
            
        注意：
            - 使用标记价格触发以防止价格操纵
            - 触发时以市价（-1）执行订单
            - 设置新订单前自动取消旧订单
            - 部分失败时继续（一个订单可能成功而另一个失败）
        """
        symbol = symbol or config.symbol
        
        try:
            # Cancel old orders first
            try:
                print("🔄 设置新订单前，先取消该交易对的所有旧止盈止损订单...")
                self.cancel_tp_sl_orders(symbol, None)
                time.sleep(0.5)
            except Exception as e:
                print(f"⚠️ 取消旧订单时出错（继续执行）: {e}")
            
            markets = self.reload_markets()
            market = markets[symbol]
            inst_id = market['id']
            trade_side = 'sell' if position_side == 'long' else 'buy'
            
            order_ids = {'tp_order_id': None, 'sl_order_id': None}
            
            # Set stop loss
            if stop_loss_price > 0:
                try:
                    params = {
                        'instId': inst_id,
                        'tdMode': 'cross',
                        'side': trade_side,
                        'ordType': 'conditional',
                        'sz': str(position_size),
                        'slTriggerPx': str(stop_loss_price),
                        'slOrdPx': '-1',
                        'slTriggerPxType': 'mark',
                    }
                    response = self.exchange.request('trade/order-algo', 'private', 'POST', params)
                    if response and response.get('code') == '0':
                        order_ids['sl_order_id'] = response.get('data', [{}])[0].get('algoId')
                        print(f"✅ 止损订单设置成功: {stop_loss_price:.2f} (订单ID: {order_ids['sl_order_id']})")
                    else:
                        print(f"⚠️ 止损订单设置失败: {response.get('msg', '未知错误')}")
                except Exception as e:
                    print(f"⚠️ 设置止损订单时出错: {e}")
                    print("⚠️ 止损订单设置失败，将使用代码监控作为备用")
            
            # Set take profit
            if take_profit_price > 0:
                try:
                    params = {
                        'instId': inst_id,
                        'tdMode': 'cross',
                        'side': trade_side,
                        'ordType': 'conditional',
                        'sz': str(position_size),
                        'tpTriggerPx': str(take_profit_price),
                        'tpOrdPx': '-1',
                        'tpTriggerPxType': 'mark',
                    }
                    response = self.exchange.request('trade/order-algo', 'private', 'POST', params)
                    if response and response.get('code') == '0':
                        order_ids['tp_order_id'] = response.get('data', [{}])[0].get('algoId')
                        print(f"✅ 止盈订单设置成功: {take_profit_price:.2f} (订单ID: {order_ids['tp_order_id']})")
                    else:
                        print(f"⚠️ 止盈订单设置失败: {response.get('msg', '未知错误')}")
                except Exception as e:
                    print(f"⚠️ 设置止盈订单时出错: {e}")
                    print("⚠️ 止盈订单设置失败，将使用代码监控作为备用")
            
            if order_ids['tp_order_id'] or order_ids['sl_order_id']:
                return order_ids
            return None
            
        except Exception as e:
            print(f"❌ 设置止盈止损订单失败: {e}")
            traceback.print_exc()
            return None
    
    def cancel_tp_sl_orders(
        self,
        symbol: Optional[str] = None,
        order_ids: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        Cancel take-profit and stop-loss conditional orders.
        
        Can cancel specific orders by ID or all conditional orders for a symbol.
        Gracefully handles already-cancelled or non-existent orders.
        
        Args:
            symbol: Trading pair symbol (default: from config)
            order_ids: Specific order IDs to cancel {'tp_order_id': str, 'sl_order_id': str}
                      If None, cancels ALL conditional orders for the symbol
            
        Returns:
            True if any orders were cancelled or operation completed successfully
            False if operation failed
            
        Note:
            - Silently ignores 404/Not Found errors (already cancelled)
            - Queries all pending conditional orders if order_ids not provided
            - Safe to call even if no orders exist

        ---

        取消止盈止损条件单。
        
        可以按 ID 取消特定订单，或取消某个交易对的所有条件单。
        优雅地处理已取消或不存在的订单。
        
        参数：
            symbol: 交易对符号（默认：从配置读取）
            order_ids: 要取消的特定订单 ID {'tp_order_id': str, 'sl_order_id': str}
                      如果为 None，则取消该交易对的所有条件单
            
        返回：
            如果有订单被取消或操作成功完成则返回 True
            如果操作失败则返回 False
            
        注意：
            - 静默忽略 404/未找到错误（已取消）
            - 如果未提供 order_ids，则查询所有待处理的条件单
            - 即使没有订单也可以安全调用
        """
        symbol = symbol or config.symbol
        
        try:
            markets = self.reload_markets()
            market = markets[symbol]
            inst_id = market['id']
            
            # Cancel specific orders
            if order_ids:
                cancelled = False
                
                if order_ids.get('tp_order_id'):
                    try:
                        cancel_params = [{'algoId': order_ids['tp_order_id'], 'instId': inst_id}]
                        response = self.exchange.request('trade/cancel-algos', 'private', 'POST', {'data': cancel_params})
                        if response and response.get('code') == '0':
                            data = response.get('data', [])
                            if data and data[0].get('sCode', '0') == '0':
                                print(f"✅ 止盈订单已取消: {order_ids['tp_order_id']}")
                                cancelled = True
                    except Exception as e:
                        if '404' not in str(e) and 'Not Found' not in str(e):
                            print(f"❌ 取消止盈订单失败: {e}")
                
                if order_ids.get('sl_order_id'):
                    try:
                        cancel_params = [{'algoId': order_ids['sl_order_id'], 'instId': inst_id}]
                        response = self.exchange.request('trade/cancel-algos', 'private', 'POST', {'data': cancel_params})
                        if response and response.get('code') == '0':
                            data = response.get('data', [])
                            if data and data[0].get('sCode', '0') == '0':
                                print(f"✅ 止损订单已取消: {order_ids['sl_order_id']}")
                                cancelled = True
                    except Exception as e:
                        if '404' not in str(e) and 'Not Found' not in str(e):
                            print(f"❌ 取消止损订单失败: {e}")
                
                return cancelled
            
            # Cancel all conditional orders for the symbol
            cancelled_count = 0
            orders = []
            params = {'instType': 'SWAP', 'instId': inst_id, 'ordType': 'conditional'}
            
            try:
                response = self.exchange.request('trade/orders-algo-pending', 'private', 'GET', params)
                if response and response.get('code') == '0':
                    orders = response.get('data', [])
            except Exception:
                try:
                    response = self.exchange.request('trade/orders-algo-pending', 'private', 'GET', {'instType': 'SWAP'})
                    if response and response.get('code') == '0':
                        all_orders = response.get('data', [])
                        orders = [o for o in all_orders if o.get('instId') == inst_id]
                except Exception as e2:
                    print(f"⚠️ 查询策略订单失败: {e2}")
                    return True
            
            for order in orders:
                algo_id = order.get('algoId')
                if algo_id:
                    try:
                        cancel_params = [{'algoId': algo_id, 'instId': inst_id}]
                        cancel_response = self.exchange.request('trade/cancel-algos', 'private', 'POST', {'data': cancel_params})
                        if cancel_response and cancel_response.get('code') == '0':
                            data = cancel_response.get('data', [])
                            if data and data[0].get('sCode', '0') == '0':
                                cancelled_count += 1
                    except Exception:
                        pass
            
            if cancelled_count > 0:
                print(f"✅ 已取消 {cancelled_count} 个策略订单")
            else:
                print("ℹ️ 没有找到需要取消的策略订单")
            
            return True
            
        except Exception as e:
            print(f"❌ 取消止盈止损订单失败: {e}")
            return False
    
    def update_tp_sl_orders(
        self,
        position_side: str,
        position_size: float,
        stop_loss_price: float,
        take_profit_price: float,
        symbol: Optional[str] = None,
        old_order_ids: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Optional[str]]]:
        """
        Update TP/SL orders by cancelling old and creating new ones.
        
        This is the recommended method for updating TP/SL levels as it:
        1. Verifies the position still exists and matches expected parameters
        2. Cancels old orders to prevent conflicts
        3. Creates new orders with updated prices
        
        Safety Features:
        - Verifies actual position exists before updating
        - Validates position side matches expectation
        - Cancels orphaned orders if position no longer exists
        
        Args:
            position_side: 'long' or 'short'
            position_size: Position size in contracts
            stop_loss_price: New stop loss trigger price
            take_profit_price: New take profit trigger price
            symbol: Trading pair symbol (default: from config)
            old_order_ids: Previous order IDs to cancel
            
        Returns:
            New order IDs dictionary or None if position validation fails
            
        Note:
            Will NOT create new orders if position verification fails,
            preventing orphaned TP/SL orders without corresponding positions.

        ---

        通过取消旧订单并创建新订单来更新止盈止损。
        
        这是更新止盈止损水平的推荐方法，因为它：
        1. 验证持仓仍然存在且与预期参数匹配
        2. 取消旧订单以防止冲突
        3. 创建价格已更新的新订单
        
        安全特性：
        - 更新前验证实际持仓是否存在
        - 验证持仓方向与预期匹配
        - 如果持仓不再存在则取消孤立订单
        
        参数：
            position_side: 'long' 或 'short'
            position_size: 持仓大小（合约数）
            stop_loss_price: 新的止损触发价格
            take_profit_price: 新的止盈触发价格
            symbol: 交易对符号（默认：从配置读取）
            old_order_ids: 要取消的旧订单 ID
            
        返回：
            新订单 ID 字典，如果持仓验证失败则返回 None
            
        注意：
            如果持仓验证失败，将不会创建新订单，
            防止创建没有对应持仓的孤立止盈止损订单。
        """
        symbol = symbol or config.symbol
        
        try:
            # Verify actual position before updating
            try:
                actual_position = self.get_current_position(symbol)
                if not actual_position or actual_position['size'] <= 0:
                    print("⚠️ 更新止盈止损订单时检测到实际无持仓，取消操作，避免创建残留订单")
                    if old_order_ids:
                        self.cancel_tp_sl_orders(symbol, old_order_ids)
                    return None
                if actual_position['side'] != position_side:
                    print(f"⚠️ 更新止盈止损订单时检测到持仓方向不匹配（实际: {actual_position['side']}, 预期: {position_side}），取消操作")
                    if old_order_ids:
                        self.cancel_tp_sl_orders(symbol, old_order_ids)
                    return None
            except Exception as e:
                print(f"⚠️ 验证实际持仓时出错，继续执行订单更新: {e}")
            
            # Cancel old orders
            if old_order_ids:
                self.cancel_tp_sl_orders(symbol, old_order_ids)
                time.sleep(0.5)
            
            # Create new orders
            return self.set_tp_sl_orders(position_side, position_size, stop_loss_price, take_profit_price, symbol)
            
        except Exception as e:
            print(f"❌ 更新止盈止损订单失败: {e}")
            return None
    
    # ==================== Trade History ====================
    
    def fetch_my_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent trade history.
        
        Args:
            symbol: Trading pair symbol (default: from config)
            limit: Maximum number of trades to fetch
            
        Returns:
            List of trade dictionaries
        """
        symbol = symbol or config.symbol
        return self.exchange.fetch_my_trades(symbol, limit=limit)


# ==================== Module Exports ====================

# Singleton instance - automatically initialized on import
# Markets are loaded during initialization, making them immediately available
# 单例实例 - 导入时自动初始化
# 市场数据在初始化期间加载，使其立即可用
exchange_service = ExchangeService()

__all__ = ["ExchangeService", "exchange_service"]

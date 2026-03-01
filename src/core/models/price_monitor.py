from datetime import datetime


class PriceMonitor:
    """Price monitor tracking trailing stops and position metadata."""

    def __init__(self):
        self.current_position_info = None

    def update_position_info(self, signal_data, price_data, position_size):
        entry_price = price_data.get("price")
        position_side = signal_data.get("signal", "HOLD").lower()
        self.current_position_info = {
            "position_side": position_side,
            "position_size": position_size,
            "entry_price": entry_price,
            "stop_loss": signal_data.get("stop_loss"),
            "take_profit": signal_data.get("take_profit"),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trailing_stop_activated": False,
            "highest_profit": entry_price if position_side == "long" else 0,
            "lowest_profit": entry_price if position_side == "short" else 0,
            "peak_profit": 0,
            "trailing_stop_price": None,
        }

    def clear_position_info(self):
        self.current_position_info = None

    def initialize_existing_position(self, current_position, price_data):
        entry_price = current_position.get("entry_price", price_data.get("price"))
        side = current_position.get("side")
        self.current_position_info = {
            "position_side": side,
            "position_size": current_position.get("size", 0),
            "entry_price": entry_price,
            "stop_loss": current_position.get("stop_loss", None),
            "take_profit": current_position.get("take_profit", None),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trailing_stop_activated": False,
            "highest_profit": entry_price if side == "long" else 0,
            "lowest_profit": entry_price if side == "short" else 0,
            "peak_profit": 0,
            "trailing_stop_price": None,
        }

    def update_with_price(self, current_price: float, trailing_window: float = 0.005):
        """Evolve trailing-stop stats using the latest trade price.

        trailing_window is a percentage as a decimal (0.005 = 0.5%).
        """

        if not self.current_position_info:
            return

        info = self.current_position_info
        entry = info.get("entry_price") or current_price
        side = info.get("position_side")

        if side == "long":
            info["highest_profit"] = max(info.get("highest_profit", entry), current_price)
            profit_pct = (current_price - entry) / entry * 100 if entry else 0
            if profit_pct > info.get("peak_profit", 0):
                info["peak_profit"] = profit_pct
            if profit_pct >= trailing_window * 100:
                info["trailing_stop_activated"] = True
                info["trailing_stop_price"] = info["highest_profit"] * (1 - trailing_window)
        elif side == "short":
            info["lowest_profit"] = min(info.get("lowest_profit", entry), current_price)
            profit_pct = (entry - current_price) / entry * 100 if entry else 0
            if profit_pct > info.get("peak_profit", 0):
                info["peak_profit"] = profit_pct
            if profit_pct >= trailing_window * 100:
                info["trailing_stop_activated"] = True
                info["trailing_stop_price"] = info["lowest_profit"] * (1 + trailing_window)

    def stop_monitoring(self):
        self.clear_position_info()


def initialize_price_monitor() -> PriceMonitor:
    return PriceMonitor()
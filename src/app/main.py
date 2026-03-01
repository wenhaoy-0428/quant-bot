"""Bot entry point.

Creates a TradingBot and calls run(). That's it.
"""

from core.models.trading_bot import TradingBot


def main() -> None:
    TradingBot().run()


if __name__ == "__main__":
    main()

import pandas as pd

from trading.strategy.base import Action, Signal


class BuyAndHoldStrategy:
    """Buys on the first available bar and never sells. Not a real trading
    strategy -- a baseline benchmark to check whether an active strategy is
    actually earning its complexity, or just riding the market."""

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        return bars.copy()

    def signal_for_row(self, symbol: str, row: pd.Series, in_position: bool) -> Signal:
        price = row["close"]
        if pd.isna(price):
            return Signal(symbol, Action.HOLD, price, reason="warming up")
        if not in_position:
            return Signal(symbol, Action.BUY, price, reason="buy and hold")
        return Signal(symbol, Action.HOLD, price, reason="holding")

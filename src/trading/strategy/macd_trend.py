import pandas as pd

from trading.indicators import atr, macd, sma
from trading.strategy.base import Action, Signal


class MacdTrendStrategy:
    """Long-only momentum: only take MACD crossovers that agree with the
    dominant (200-day) trend, to filter out whipsaws in a choppy or
    downtrending market.

    Entry: MACD line crosses above its signal line AND price is above the
    200-day SMA. Exit: MACD crosses back below its signal line, or an
    ATR-based stop-loss / take-profit is hit.
    """

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        trend_window: int = 200,
        atr_window: int = 14,
        atr_stop_mult: float = 2.5,
        atr_target_mult: float = 5.0,
    ):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.trend_window = trend_window
        self.atr_window = atr_window
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        macd_line, signal_line, hist = macd(df["close"], self.fast, self.slow, self.signal)
        df["macd"], df["macd_signal"], df["macd_hist"] = macd_line, signal_line, hist
        df["sma_trend"] = sma(df["close"], self.trend_window)
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        df["macd_above_signal"] = df["macd"] > df["macd_signal"]
        return df

    def signal_for_row(self, symbol: str, row: pd.Series, in_position: bool) -> Signal:
        price = row["close"]
        if any(pd.isna(row[c]) for c in ("macd", "macd_signal", "sma_trend", "atr")):
            return Signal(symbol, Action.HOLD, price, reason="warming up")

        if not in_position:
            entry_ok = bool(row["macd_above_signal"]) and price > row["sma_trend"]
            if entry_ok:
                stop = price - self.atr_stop_mult * row["atr"]
                target = price + self.atr_target_mult * row["atr"]
                return Signal(symbol, Action.BUY, price, stop, target, "macd momentum entry")
            return Signal(symbol, Action.HOLD, price, reason="no entry signal")

        if not row["macd_above_signal"]:
            return Signal(symbol, Action.SELL, price, reason="macd crossed below signal")
        return Signal(symbol, Action.HOLD, price, reason="holding")

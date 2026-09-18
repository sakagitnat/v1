import pandas as pd

from trading.indicators import atr, bollinger_bands, rsi
from trading.strategy.base import Action, Signal


class MeanReversionStrategy:
    """Long-only mean reversion: buy an oversold dip, sell once price reverts
    back to the average.

    Entry: price closes at or below the lower Bollinger Band AND RSI confirms
    oversold conditions (avoids buying a stock that's merely quiet/low-volatility).
    Exit: price reverts to the middle band (the moving average), or an
    ATR-based stop-loss / take-profit is hit.
    """

    def __init__(
        self,
        bb_window: int = 20,
        bb_std: float = 2.0,
        rsi_window: int = 14,
        rsi_oversold: float = 30.0,
        atr_window: int = 14,
        atr_stop_mult: float = 2.0,
        atr_target_mult: float = 3.0,
    ):
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.rsi_window = rsi_window
        self.rsi_oversold = rsi_oversold
        self.atr_window = atr_window
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        upper, mid, lower = bollinger_bands(df["close"], self.bb_window, self.bb_std)
        df["bb_upper"], df["bb_mid"], df["bb_lower"] = upper, mid, lower
        df["rsi"] = rsi(df["close"], self.rsi_window)
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        return df

    def signal_for_row(self, symbol: str, row: pd.Series, in_position: bool) -> Signal:
        price = row["close"]
        if any(pd.isna(row[c]) for c in ("bb_lower", "bb_mid", "rsi", "atr")):
            return Signal(symbol, Action.HOLD, price, reason="warming up")

        if not in_position:
            entry_ok = price <= row["bb_lower"] and row["rsi"] <= self.rsi_oversold
            if entry_ok:
                stop = price - self.atr_stop_mult * row["atr"]
                target = price + self.atr_target_mult * row["atr"]
                return Signal(symbol, Action.BUY, price, stop, target, "mean-reversion entry")
            return Signal(symbol, Action.HOLD, price, reason="no entry signal")

        if price >= row["bb_mid"]:
            return Signal(symbol, Action.SELL, price, reason="reverted to mean")
        return Signal(symbol, Action.HOLD, price, reason="holding")

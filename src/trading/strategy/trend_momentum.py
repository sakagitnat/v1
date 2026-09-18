import pandas as pd

from trading.indicators import atr, ema, rsi
from trading.strategy.base import Action, Signal


class TrendMomentumStrategy:
    """Long-only trend-following strategy with a momentum filter.

    Entry (all must hold):
      - fast EMA above slow EMA (uptrend)
      - price above the slow EMA
      - RSI between rsi_low and rsi_high (skips both weak and exhausted moves)

    Exit:
      - fast EMA crosses back below slow EMA, or
      - price hits the ATR-based stop-loss / take-profit (checked by the caller,
        since that needs the bar's high/low rather than just signal_for_row's close)
    """

    def __init__(
        self,
        fast_window: int = 20,
        slow_window: int = 50,
        rsi_window: int = 14,
        rsi_low: float = 40.0,
        rsi_high: float = 70.0,
        atr_window: int = 14,
        atr_stop_mult: float = 2.0,
        atr_target_mult: float = 4.0,
    ):
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.rsi_window = rsi_window
        self.rsi_low = rsi_low
        self.rsi_high = rsi_high
        self.atr_window = atr_window
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        df["ema_fast"] = ema(df["close"], self.fast_window)
        df["ema_slow"] = ema(df["close"], self.slow_window)
        df["rsi"] = rsi(df["close"], self.rsi_window)
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        df["trend_up"] = df["ema_fast"] > df["ema_slow"]
        return df

    def signal_for_row(self, symbol: str, row: pd.Series, in_position: bool) -> Signal:
        price = row["close"]
        if any(pd.isna(row[c]) for c in ("ema_fast", "ema_slow", "rsi", "atr")):
            return Signal(symbol, Action.HOLD, price, reason="warming up")

        if not in_position:
            entry_ok = (
                bool(row["trend_up"])
                and price > row["ema_slow"]
                and self.rsi_low <= row["rsi"] <= self.rsi_high
            )
            if entry_ok:
                stop = price - self.atr_stop_mult * row["atr"]
                target = price + self.atr_target_mult * row["atr"]
                return Signal(symbol, Action.BUY, price, stop, target, "trend+momentum entry")
            return Signal(symbol, Action.HOLD, price, reason="no entry signal")

        if not row["trend_up"]:
            return Signal(symbol, Action.SELL, price, reason="trend flipped down")
        return Signal(symbol, Action.HOLD, price, reason="holding")

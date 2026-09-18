import pandas as pd

from trading.indicators import atr, donchian_channel
from trading.strategy.base import Action, Signal


class BreakoutStrategy:
    """Long-only Donchian channel breakout -- the classic "Turtle Trading"
    idea: buy a new N-day high, on the theory that a stock breaking out of a
    range is starting a new trend.

    Entry: today's close is above the highest high of the prior
    `entry_window` bars. Exit: close drops below the lowest low of the prior
    `exit_window` bars, or an ATR-based stop-loss / take-profit is hit.

    Defaults tuned by scripts/optimize_strategy.py (2026-09-18): grid-searched
    on 2019-2023, validated on the untouched 2024-present holdout, where it
    raised win rate from 45.5% to 68.6% (Sharpe 1.26 -> 0.94, CAGR 13.9% ->
    8.1% -- a deliberate trade: smaller, more frequent wins over fewer,
    larger ones). See that script's docstring for the train/test methodology.
    """

    def __init__(
        self,
        entry_window: int = 10,
        exit_window: int = 15,
        atr_window: int = 14,
        atr_stop_mult: float = 2.5,
        atr_target_mult: float = 1.5,
    ):
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.atr_window = atr_window
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        entry_high, _ = donchian_channel(df["high"], df["low"], self.entry_window)
        _, exit_low = donchian_channel(df["high"], df["low"], self.exit_window)
        df["entry_high"] = entry_high
        df["exit_low"] = exit_low
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        return df

    def signal_for_row(self, symbol: str, row: pd.Series, in_position: bool) -> Signal:
        price = row["close"]
        if any(pd.isna(row[c]) for c in ("entry_high", "exit_low", "atr")):
            return Signal(symbol, Action.HOLD, price, reason="warming up")

        if not in_position:
            if price > row["entry_high"]:
                stop = price - self.atr_stop_mult * row["atr"]
                target = price + self.atr_target_mult * row["atr"]
                return Signal(symbol, Action.BUY, price, stop, target, "breakout entry")
            return Signal(symbol, Action.HOLD, price, reason="no breakout")

        if price < row["exit_low"]:
            return Signal(symbol, Action.SELL, price, reason="broke below exit channel")
        return Signal(symbol, Action.HOLD, price, reason="holding")

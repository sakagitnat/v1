"""RSI Reversion (CFD) -- src/trading/cfd/rsi_reversion.py

A second ranging-market strategy, deliberately different from
MeanReversionStrategy rather than a parameter variant of it.
MeanReversionStrategy fades *price relative to Bollinger Bands*; this
strategy fades *momentum exhaustion* measured by RSI. The two can agree
on the same trade, but they are built from different evidence and can
therefore diversify the ranging bucket instead of duplicating the same
entry rule.

The ADX gate is essential. RSI can stay oversold throughout a strong
downtrend or overbought throughout a strong uptrend, so using RSI alone
would repeatedly fade a real trend. Requiring ADX to be at or below a
very low flat-market threshold makes the strategy explicitly refuse
entries unless trend strength is weak enough to support the
mean-reversion thesis. This threshold is intentionally stricter than the
project's normal trending classification: the entry should require
evidence of *no meaningful trend*, not merely "not strongly trending."

Entry: while flat (ADX <= adx_flat_threshold), RSI <= oversold opens a
long and RSI >= overbought opens a short. Exit: a long closes once RSI
reaches the neutral midpoint (>= 50); a short closes once RSI falls back
to neutral (<= 50). ATR-based stop-loss/take-profit levels provide the
same protective exit shape as the project's other CFD strategies so the
structural difference under test is the RSI+ADX entry/exit thesis.

UNVALIDATED as of writing. Constructor defaults are placeholders, not
live-trading recommendations. They must go through the same TRAIN/TEST
and Research Lab validation pipeline as every other candidate before a
version can progress beyond research.
"""
import pandas as pd

from trading.indicators import adx, atr, rsi
from trading.strategy.base import Action, Signal


class RsiReversionStrategy:
    def __init__(
        self,
        rsi_window: int = 14,
        rsi_oversold: float = 25.0,
        rsi_overbought: float = 75.0,
        adx_window: int = 14,
        adx_flat_threshold: float = 15.0,
        atr_window: int = 14,
        atr_stop_mult: float = 2.0,
        atr_target_mult: float = 1.5,
    ):
        self.rsi_window = rsi_window
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.adx_window = adx_window
        self.adx_flat_threshold = adx_flat_threshold
        self.atr_window = atr_window
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        df["rsi"] = rsi(df["close"], self.rsi_window)
        df["adx"] = adx(df["high"], df["low"], df["close"], self.adx_window)
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        return df

    def signal_for_row(
        self,
        instrument: str,
        row: pd.Series,
        prev_row: pd.Series,
        in_position: str | None,
    ) -> Signal:
        """Return the current RSI-reversion decision.

        prev_row is accepted for interface parity with every other CFD
        strategy but is intentionally unused: entries depend on the current
        completed bar's RSI/ADX state, not on detecting a one-bar crossover.
        """
        price = row["close"]
        needed = ("rsi", "adx", "atr")
        if any(c not in row.index or pd.isna(row[c]) for c in needed):
            return Signal(instrument, Action.HOLD, price, reason="warming up")

        if in_position == "long":
            if row["rsi"] >= 50:
                return Signal(instrument, Action.SELL, price, reason="RSI reverted to neutral (close long)")
            return Signal(instrument, Action.HOLD, price, reason="holding long, RSI still below neutral")

        if in_position == "short":
            if row["rsi"] <= 50:
                return Signal(instrument, Action.BUY, price, reason="RSI reverted to neutral (cover short)")
            return Signal(instrument, Action.HOLD, price, reason="holding short, RSI still above neutral")

        if row["adx"] > self.adx_flat_threshold:
            return Signal(instrument, Action.HOLD, price, reason="ADX too high for flat-market RSI reversion")

        if row["rsi"] <= self.rsi_oversold:
            stop = price - self.atr_stop_mult * row["atr"]
            target = price + self.atr_target_mult * row["atr"]
            return Signal(instrument, Action.BUY, price, stop, target, "flat market + RSI oversold (long entry)")

        if row["rsi"] >= self.rsi_overbought:
            stop = price + self.atr_stop_mult * row["atr"]
            target = price - self.atr_target_mult * row["atr"]
            return Signal(instrument, Action.SELL, price, stop, target, "flat market + RSI overbought (short entry)")

        return Signal(instrument, Action.HOLD, price, reason="RSI not extreme enough for entry")

import pandas as pd

from trading.indicators import atr, ema
from trading.strategy.base import Action, Signal


class EmaCrossoverStrategy:
    """Intraday EMA crossover, long or short -- a starting point for the
    CFD/forex system, not yet backtested or tuned (OANDA's candle history
    needs a live API token to fetch, same as everything else in cfd/).

    Entry: fast EMA crosses above slow EMA -> long; crosses below -> short.
    Exit: the opposite crossover, or an ATR-based stop-loss/take-profit.
    Meant for short bars (e.g. 15-minute candles) where a handful of these
    crossovers can happen in a single trading day -- unlike the stock
    system's daily-bar Breakout strategy, this is meant to open and close
    positions same-day, sometimes several times a day.
    """

    def __init__(
        self,
        fast_span: int = 12,
        slow_span: int = 26,
        atr_window: int = 14,
        atr_stop_mult: float = 1.5,
        atr_target_mult: float = 2.5,
    ):
        self.fast_span = fast_span
        self.slow_span = slow_span
        self.atr_window = atr_window
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        df["fast_ema"] = ema(df["close"], self.fast_span)
        df["slow_ema"] = ema(df["close"], self.slow_span)
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        return df

    def signal_for_row(self, instrument: str, row: pd.Series, prev_row: pd.Series, in_position: str | None) -> Signal:
        """in_position is None (flat), "long", or "short" -- which side is
        currently open, if any. prev_row is the immediately preceding bar,
        needed to detect the crossover moment rather than just the
        fast/slow ordering (which stays "crossed" for many bars after)."""
        price = row["close"]
        needed = ("fast_ema", "slow_ema", "atr")
        if any(pd.isna(row[c]) for c in needed) or any(pd.isna(prev_row[c]) for c in needed):
            return Signal(instrument, Action.HOLD, price, reason="warming up")

        crossed_up = prev_row["fast_ema"] <= prev_row["slow_ema"] and row["fast_ema"] > row["slow_ema"]
        crossed_down = prev_row["fast_ema"] >= prev_row["slow_ema"] and row["fast_ema"] < row["slow_ema"]

        if in_position == "long" and crossed_down:
            return Signal(instrument, Action.SELL, price, reason="fast EMA crossed below slow EMA (close long)")
        if in_position == "short" and crossed_up:
            return Signal(instrument, Action.BUY, price, reason="fast EMA crossed above slow EMA (cover short)")

        if in_position is None:
            if crossed_up:
                stop = price - self.atr_stop_mult * row["atr"]
                target = price + self.atr_target_mult * row["atr"]
                return Signal(instrument, Action.BUY, price, stop, target, "fast EMA crossed above slow EMA")
            if crossed_down:
                stop = price + self.atr_stop_mult * row["atr"]
                target = price - self.atr_target_mult * row["atr"]
                return Signal(instrument, Action.SELL, price, stop, target, "fast EMA crossed below slow EMA (short entry)")

        return Signal(instrument, Action.HOLD, price, reason="no crossover")

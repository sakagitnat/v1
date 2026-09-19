import pandas as pd

from trading.indicators import atr, donchian_channel
from trading.strategy.base import Action, Signal


class DonchianBreakoutStrategy:
    """Long/short Donchian channel breakout for Deriv Multipliers --
    the CFD counterpart of trading.strategy.breakout.BreakoutStrategy
    (the classic "Turtle Trading" system), extended to short as well as
    long since Multipliers support both directions and this is how the
    original Turtle system actually traded.

    Built as a genuinely different structural bet from
    EmaCrossoverStrategy, not a parameter retune of it: every risk
    level tried on EmaCrossoverStrategy across forex/gold, crypto, and
    Deriv's synthetic indices showed the same pattern (see README's
    "Backtesting" section) -- TRAIN and TEST flipping between
    catastrophic and spectacular depending on which period got the
    trend, never both survivable at once. That's consistent with a
    thin, inconsistent edge no amount of position sizing fixes.
    BreakoutStrategy won decisively in the stock system's own
    strategy comparison (beat a regime-switching ensemble on CAGR,
    Sharpe, AND max drawdown simultaneously -- see this project's
    README, stock side), so it's a credible different structure to
    test here, not an arbitrary pick.

    Entry: price closes above the highest high of the prior
    `entry_window` bars -> long; below the lowest low -> short (a wider
    lookback than the exit channel, so entries require a more
    decisive break than what triggers an exit).
    Exit: price closes below the lowest low of the prior `exit_window`
    bars (long) / above the highest high (short), or an ATR-based
    stop-loss/take-profit -- same ATR-based protective exit shape as
    EmaCrossoverStrategy, so the entry logic is the one structural
    variable being tested, not the exit.

    UNVALIDATED as of writing -- see scripts/optimize_cfd_breakout.py
    for the TRAIN/TEST grid search this needs before any parameter
    choice here is trusted; these constructor defaults are placeholders
    (loosely following the stock BreakoutStrategy's own validated
    30/10 window shape), not validated numbers.
    """

    def __init__(
        self,
        entry_window: int = 30,
        exit_window: int = 10,
        atr_window: int = 14,
        atr_stop_mult: float = 2.5,
        atr_target_mult: float = 4.0,
    ):
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.atr_window = atr_window
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        entry_high, entry_low = donchian_channel(df["high"], df["low"], self.entry_window)
        exit_high, exit_low = donchian_channel(df["high"], df["low"], self.exit_window)
        df["entry_high"] = entry_high
        df["entry_low"] = entry_low
        df["exit_high"] = exit_high
        df["exit_low"] = exit_low
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        return df

    def signal_for_row(self, symbol: str, row: pd.Series, prev_row: pd.Series, in_position: str | None) -> Signal:
        """prev_row is accepted for interface parity with
        EmaCrossoverStrategy (CfdBacktestEngine/scheduler always pass
        it) but unused -- a breakout, unlike a crossover, is fully
        determined by the current bar's close against channels already
        computed from strictly prior bars (donchian_channel excludes
        the current bar by construction), no "did we just cross" check
        needed."""
        price = row["close"]
        needed = ("entry_high", "entry_low", "exit_high", "exit_low", "atr")
        if any(pd.isna(row[c]) for c in needed):
            return Signal(symbol, Action.HOLD, price, reason="warming up")

        if in_position == "long":
            if price < row["exit_low"]:
                return Signal(symbol, Action.SELL, price, reason="broke below exit channel (close long)")
            return Signal(symbol, Action.HOLD, price, reason="holding long")

        if in_position == "short":
            if price > row["exit_high"]:
                return Signal(symbol, Action.BUY, price, reason="broke above exit channel (cover short)")
            return Signal(symbol, Action.HOLD, price, reason="holding short")

        if price > row["entry_high"]:
            stop = price - self.atr_stop_mult * row["atr"]
            target = price + self.atr_target_mult * row["atr"]
            return Signal(symbol, Action.BUY, price, stop, target, "broke above entry channel (long entry)")
        if price < row["entry_low"]:
            stop = price + self.atr_stop_mult * row["atr"]
            target = price - self.atr_target_mult * row["atr"]
            return Signal(symbol, Action.SELL, price, stop, target, "broke below entry channel (short entry)")

        return Signal(symbol, Action.HOLD, price, reason="no breakout")

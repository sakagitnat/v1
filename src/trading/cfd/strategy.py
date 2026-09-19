import pandas as pd

from trading.indicators import atr, ema
from trading.strategy.base import Action, Signal


class EmaCrossoverStrategy:
    """Intraday EMA crossover, long or short -- runs on Deriv Multipliers
    (gold + major forex pairs).

    Entry: fast EMA crosses above slow EMA -> long; crosses below -> short.
    Exit: the opposite crossover, or an ATR-based stop-loss/take-profit.

    Defaults are validated against ~2 years of hourly (H1) history via
    scripts/optimize_cfd_strategy.py's train/test split, not a guess:
    the original defaults (12/26/1.5/2.5, aimed at 15-minute bars) scored
    a -30.8% TRAIN CAGR and -65.5% max drawdown over that window --
    whipsaw in ranging FX/gold, not a parameter that just needed fine
    tuning. A widened search found only 2 of 81 combinations held up
    out-of-sample at all; these values are the one with the best TEST
    calmar among them (TRAIN cagr=3.4% maxdd=-19.9%, TEST cagr=4.8%
    maxdd=-13.9%, win_rate=47.6% both periods -- modest but genuinely
    consistent, unlike the flashier-looking combinations that were
    badly overfit).

    Runs on H1 (hourly) bars, not the originally-intended M15, because
    H1 is the only granularity with enough real history to trust a
    train/test split on -- Deriv's own M15 candle history only goes
    back ~3 months (a server-side limit, not a fetch bug), too short to
    validate anything against. Copying H1-validated EMA spans onto M15
    bars would silently change what they mean (15 H1 bars is 15 hours
    of lookback, not 15 x 15 minutes) -- so scheduler.py's granularity
    changed to match, rather than the parameters being ported across
    timeframes unvalidated. See cfd/backtest.py and
    scripts/optimize_cfd_strategy.py for the methodology.
    """

    def __init__(
        self,
        fast_span: int = 15,
        slow_span: int = 34,
        atr_window: int = 14,
        atr_stop_mult: float = 2.0,
        atr_target_mult: float = 2.0,
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

"""Mean Reversion (CFD) -- src/trading/cfd/mean_reversion.py

Closes part of Revision 3 gap #11 (docs/ARCHITECTURE_AUDIT.md): every
registered strategy so far (EmaCrossoverStrategy, DonchianBreakoutStrategy)
is trend-following -- so trading.cfd.regime's RANGING classification has
had no registered strategy suited to it since the Strategy Selector was
built, meaning every ranging period was a pure NO TRADE by omission, not
a deliberate design choice. This is a genuinely different structural
bet, not a parameter retune of either existing strategy: it FADES price
extremes instead of following a breakout or a crossover, which is
exactly the shape of edge that (if real) shows up specifically in a
ranging, mean-reverting market and gets destroyed in a trending one --
real diversification against the existing pool, not another correlated
trend-following variant.

Entry: price closes below the lower Bollinger Band -> long (bets the
extreme reverts back toward the mean); closes above the upper band ->
short. Exit: price reverts to the middle band (the SMA the bands are
built around) -- the mean-reversion thesis playing out -- or an
ATR-based stop-loss/take-profit backstop, the same protective shape
EmaCrossoverStrategy/DonchianBreakoutStrategy already use, so the entry
logic is the one structural variable being tested, not the exit
mechanics.

UNVALIDATED as of writing -- these constructor defaults are reasonable,
sourced placeholders (band_window/band_std are the conventional
Bollinger Band textbook defaults; atr_stop_mult/atr_target_mult mirror
DonchianBreakoutStrategy's own placeholder shape), not numbers that have
been through a TRAIN/TEST split the way EmaCrossoverStrategy's
parameters were -- see docs/ARCHITECTURE_AUDIT.md. Needs the same
optimize_cfd_*.py-style grid search before any parameter choice here is
trusted, and must clear trading.cfd.research_lab's full validation gate
before it's anything more than RESEARCH/CANDIDATE in the Strategy
Registry.
"""
import pandas as pd

from trading.indicators import atr, bollinger_bands
from trading.strategy.base import Action, Signal


class MeanReversionStrategy:
    def __init__(
        self,
        band_window: int = 20,
        band_std: float = 2.0,
        atr_window: int = 14,
        atr_stop_mult: float = 2.0,
        atr_target_mult: float = 1.5,
    ):
        self.band_window = band_window
        self.band_std = band_std
        self.atr_window = atr_window
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        upper, mid, lower = bollinger_bands(df["close"], self.band_window, self.band_std)
        df["bb_upper"] = upper
        df["bb_mid"] = mid
        df["bb_lower"] = lower
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        return df

    def signal_for_row(self, instrument: str, row: pd.Series, prev_row: pd.Series, in_position: str | None) -> Signal:
        """prev_row is accepted for interface parity with the other
        registered strategies (scheduler.py/CfdBacktestEngine always
        pass it) but unused -- like a breakout, reverting to (or
        breaching) a band is fully determined by the current bar's own
        close against bands already computed from prior-and-current
        closes, no "did we just cross" check needed."""
        price = row["close"]
        needed = ["bb_upper", "bb_mid", "bb_lower", "atr"]
        if any(c not in row.index or pd.isna(row[c]) for c in needed):
            return Signal(instrument, Action.HOLD, price, reason="warming up")

        if in_position == "long":
            if price >= row["bb_mid"]:
                return Signal(instrument, Action.SELL, price, reason="reverted to the mean (close long)")
            return Signal(instrument, Action.HOLD, price, reason="holding long, mean not reached yet")

        if in_position == "short":
            if price <= row["bb_mid"]:
                return Signal(instrument, Action.BUY, price, reason="reverted to the mean (cover short)")
            return Signal(instrument, Action.HOLD, price, reason="holding short, mean not reached yet")

        if price < row["bb_lower"]:
            stop = price - self.atr_stop_mult * row["atr"]
            target = price + self.atr_target_mult * row["atr"]
            return Signal(instrument, Action.BUY, price, stop, target, "closed below the lower Bollinger Band (long entry)")
        if price > row["bb_upper"]:
            stop = price + self.atr_stop_mult * row["atr"]
            target = price - self.atr_target_mult * row["atr"]
            return Signal(instrument, Action.SELL, price, stop, target, "closed above the upper Bollinger Band (short entry)")

        return Signal(instrument, Action.HOLD, price, reason="inside the bands, no extreme")

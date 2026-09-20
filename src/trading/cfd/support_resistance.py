"""Support/Resistance Reversion (CFD) -- src/trading/cfd/support_resistance.py

Third attempt at Revision 3 gap #11 (strategy pool diversity for the
"ranging" regime), and the first genuinely different DATA
REPRESENTATION, not just a different formula over the same close-price
input. `mean_reversion@v1` (retired) faded deviation from a Bollinger
Band (a statistical band over closes); `rsi_reversion@v1` (retired)
faded RSI momentum exhaustion (an oscillator over closes). Both are
"how far/fast has price moved" measures. This strategy instead reads
actual price STRUCTURE -- confirmed swing highs and swing lows (local
turning points in the high/low series) -- and fades price when it
revisits a level the market has already respected before. See GitHub
issue #5 (the joint Claude/GPT design discussion) for why this was
picked as the third candidate specifically: the two retired attempts
share a data representation (derived statistics over closes) that
already failed twice, so the next candidate needed to use different raw
information, not just a different formula over the same information.

Pivot detection, and why it can't look ahead: a bar's high is a
"confirmed swing high" only when it's STRICTLY higher than every bar in
the `pivot_window` bars immediately before AND after it -- but a live
system (or an honest backtest) can only know the "after" half once
those later bars actually exist, `pivot_window` bars later. `prepare()`
computes the two flanking windows separately (needing future bars to
check the "after" side) and then explicitly `shift()`s the confirmed
result forward by `pivot_window` bars before it's ever used in
`signal_for_row()` -- so a pivot never informs a decision before it
could genuinely have been known at the time. This is the single most
important correctness property of this module; skipping the shift would
silently leak future information into every backtest run against it.

Entry: price's low touches at or below the most recently confirmed
support level (within `touch_threshold_pct`) -> long, betting the level
holds again; price's high touches at or above the most recently
confirmed resistance level -> short. Exit: price reverts to the
midpoint between the current support and resistance levels (the same
"reversion is the thesis playing out" exit shape `mean_reversion.py`'s
middle-band exit and `rsi_reversion.py`'s neutral-RSI exit already use),
or an ATR-based stop/target backstop anchored just past the level
itself -- same protective shape every other CFD strategy here uses, so
the entry logic (structure-based, not indicator-based) is the one
variable under test, not the exit mechanics.

UNVALIDATED as of writing -- these constructor defaults are reasonable,
sourced placeholders (pivot_window mirrors common "fractal" pivot
lookbacks; touch_threshold_pct is a small buffer since exact price-to-
the-tick touches are rare; ATR multipliers mirror the shape the other
two ranging-regime attempts used), not numbers that have been through a
TRAIN/TEST split. Needs the same optimize_cfd_*.py-style grid search
before any parameter choice here is trusted, and must clear
trading.cfd.research_lab's full validation gate before it's anything
more than RESEARCH/CANDIDATE in the Strategy Registry.
"""
import pandas as pd

from trading.indicators import atr
from trading.strategy.base import Action, Signal


class SupportResistanceReversionStrategy:
    def __init__(
        self,
        pivot_window: int = 5,
        touch_threshold_pct: float = 0.001,
        atr_window: int = 14,
        atr_stop_mult: float = 1.5,
        atr_target_mult: float = 2.5,
    ):
        self.pivot_window = pivot_window
        self.touch_threshold_pct = touch_threshold_pct
        self.atr_window = atr_window
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()

        # STRICT inequality against the pivot_window bars immediately
        # before and after -- not "equal to the window's min/max," which
        # would also fire on every bar of a flat/tied run (a centered
        # rolling().min() ties with several bars during a plateau, so an
        # equality check re-"confirms" a new, spurious support level
        # every time price goes flat, constantly overwriting the real
        # pivot via the ffill below). A genuinely flat run has no local
        # extremum at all, and correctly produces no pivot here -- the
        # standard "fractal" pivot definition (Bill Williams' Fractals
        # use the same strictly-higher/lower-than-N-bars-each-side
        # shape), not this project's own invention.
        left_low = df["low"].shift(1).rolling(self.pivot_window).min()
        right_low = df["low"].shift(-self.pivot_window).rolling(self.pivot_window).min()
        is_swing_low = (df["low"] < left_low) & (df["low"] < right_low)

        left_high = df["high"].shift(1).rolling(self.pivot_window).max()
        right_high = df["high"].shift(-self.pivot_window).rolling(self.pivot_window).max()
        is_swing_high = (df["high"] > left_high) & (df["high"] > right_high)

        # shift() forward by pivot_window: a pivot at bar i is only
        # confirmed once bar i+pivot_window exists -- see module
        # docstring for why this is the property that keeps this
        # strategy honestly backtestable, not a source of lookahead.
        confirmed_high = df["high"].where(is_swing_high).shift(self.pivot_window)
        confirmed_low = df["low"].where(is_swing_low).shift(self.pivot_window)

        df["resistance"] = confirmed_high.ffill()
        df["support"] = confirmed_low.ffill()
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        return df

    def signal_for_row(
        self,
        instrument: str,
        row: pd.Series,
        prev_row: pd.Series,
        in_position: str | None,
    ) -> Signal:
        """prev_row is accepted for interface parity with every other
        CFD strategy but is intentionally unused: entry/exit both depend
        only on the current bar's own high/low/close against levels
        prepare() already computed from strictly earlier, confirmed
        data -- no "did we just cross" check needed."""
        price = row["close"]
        needed = ("support", "resistance", "atr")
        if any(c not in row.index or pd.isna(row[c]) for c in needed):
            return Signal(instrument, Action.HOLD, price, reason="warming up")

        support = row["support"]
        resistance = row["resistance"]

        if in_position == "long":
            midline = (support + resistance) / 2
            if price >= midline:
                return Signal(instrument, Action.SELL, price, reason="reverted to support/resistance midline (close long)")
            return Signal(instrument, Action.HOLD, price, reason="holding long, midline not reached yet")

        if in_position == "short":
            midline = (support + resistance) / 2
            if price <= midline:
                return Signal(instrument, Action.BUY, price, reason="reverted to support/resistance midline (cover short)")
            return Signal(instrument, Action.HOLD, price, reason="holding short, midline not reached yet")

        # Both bounds matter, not just the upper/lower one facing the
        # level: "touched" means the low/high landed IN the tolerance
        # band around support/resistance, not merely "at or beyond" it.
        # A one-sided check (only row["low"] <= support*(1+pct)) is also
        # true for a low far BELOW a broken support -- e.g. support=100
        # and low=50 satisfies "50 <= 100.1" just as much as a genuine
        # 99.95 touch does. Once price is stuck below a stale support
        # (support only updates via a new confirmed pivot, which can lag
        # well behind a real breakdown), that one-sided check fires BUY
        # on every single bar while flat, not once on the real touch --
        # caught via a live grid-search run that came back with
        # multi-million-percent CAGR from ~5x the trade count any other
        # CFD strategy here produces on the same data (percentage-of-
        # equity position sizing compounds that trade count into an
        # impossible number, but the runaway trade count is the actual
        # defect). The two-sided band below is the fix.
        if support * (1 - self.touch_threshold_pct) <= row["low"] <= support * (1 + self.touch_threshold_pct):
            stop = support - self.atr_stop_mult * row["atr"]
            target = price + self.atr_target_mult * row["atr"]
            return Signal(instrument, Action.BUY, price, stop, target, "price touched confirmed support (long entry)")

        if resistance * (1 - self.touch_threshold_pct) <= row["high"] <= resistance * (1 + self.touch_threshold_pct):
            stop = resistance + self.atr_stop_mult * row["atr"]
            target = price - self.atr_target_mult * row["atr"]
            return Signal(instrument, Action.SELL, price, stop, target, "price touched confirmed resistance (short entry)")

        return Signal(instrument, Action.HOLD, price, reason="no support/resistance touch")

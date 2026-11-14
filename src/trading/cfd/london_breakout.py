import pandas as pd

from trading.indicators import atr
from trading.strategy.base import Action, Signal


class LondonBreakoutStrategy:
    """Session/time-of-day breakout for Deriv Multipliers -- structurally
    different from both EmaCrossoverStrategy (indicator crossover) and
    DonchianBreakoutStrategy (rolling price-channel breakout, no concept
    of time of day): this strategy's edge hypothesis is specifically
    that the Asian session's low-volatility range gets broken
    decisively once London desks open, a well-known FX seasonality
    pattern, not a derived statistic over an arbitrary rolling window.
    Research angle requested alongside walk-forward validation and
    meta-labeling (see docs/DECISIONS.md) -- external technique, not
    one already represented in this project's strategy pool.

    Mechanics (all hours UTC, the timezone every CFD price feed and
    PARAM_GRID elsewhere in this project already uses):
      1. ASIAN RANGE: each calendar day's high/low over
         [asian_start_hour, asian_end_hour) is recorded -- a proxy for
         the Asian session's typically tighter range, not a precise
         Tokyo-session definition.
      2. BREAKOUT WINDOW: only a bar whose hour is in
         [asian_end_hour, breakout_end_hour) can open a NEW position --
         a close above the day's Asian high -> long, below the Asian
         low -> short. Outside this window, no new entries: chasing a
         breakout hours after London opens is a different trade (and a
         different, untested hypothesis) from catching the open itself.
      3. SESSION EXIT: any open position is flat-closed once the bar's
         hour reaches session_close_hour, regardless of P&L -- the
         other half of "trade the session, don't hold it": this
         strategy's entire premise is the London-open volatility burst,
         not a multi-day directional view, so it doesn't carry
         overnight gap risk hoping for one. An ATR stop/target can still
         close the trade earlier (same protective-exit shape as the
         other two CFD strategies); the session cutoff is a backstop
         for whatever's still open, not a replacement for it.

    Stateless like EmaCrossoverStrategy/DonchianBreakoutStrategy (no
    per-day "already took today's breakout" flag): once a session-exit
    or stop/target flattens a position, a later bar inside the same
    day's breakout window could re-enter if price is still beyond the
    Asian range -- a deliberate simplification consistent with the
    rest of this project's strategy objects being pure functions of
    (row, prev_row, in_position), not something carrying hidden
    cross-bar state the backtest engine doesn't know about.

    UNVALIDATED as of writing -- see scripts/optimize_cfd_london_breakout.py
    for the TRAIN/TEST + Deflated Sharpe Ratio grid search this needs
    before any parameter choice here is trusted; these constructor
    defaults are reasonable, sourced placeholders (00:00-07:00 UTC as
    an Asian-session proxy, 07:00-10:00 UTC as the London-open breakout
    window, flat by 20:00 UTC before the NY afternoon thins out), not
    validated numbers.
    """

    def __init__(
        self,
        asian_start_hour: int = 0,
        asian_end_hour: int = 7,
        breakout_end_hour: int = 10,
        session_close_hour: int = 20,
        atr_window: int = 14,
        atr_stop_mult: float = 1.5,
        atr_target_mult: float = 3.0,
    ):
        if not 0 <= asian_start_hour < asian_end_hour < breakout_end_hour <= session_close_hour <= 24:
            raise ValueError(
                "require 0 <= asian_start_hour < asian_end_hour < breakout_end_hour <= session_close_hour <= 24"
            )
        self.asian_start_hour = asian_start_hour
        self.asian_end_hour = asian_end_hour
        self.breakout_end_hour = breakout_end_hour
        self.session_close_hour = session_close_hour
        self.atr_window = atr_window
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)

        hours = df.index.hour
        day = df.index.normalize()
        asian_mask = (hours >= self.asian_start_hour) & (hours < self.asian_end_hour)

        asian_high_by_day = df.loc[asian_mask].groupby(day[asian_mask])["high"].max()
        asian_low_by_day = df.loc[asian_mask].groupby(day[asian_mask])["low"].min()
        df["asian_high"] = asian_high_by_day.reindex(day).to_numpy()
        df["asian_low"] = asian_low_by_day.reindex(day).to_numpy()
        df["_hour"] = hours
        return df

    def _in_breakout_window(self, hour: int) -> bool:
        return self.asian_end_hour <= hour < self.breakout_end_hour

    def signal_for_row(self, symbol: str, row: pd.Series, prev_row: pd.Series, in_position: str | None) -> Signal:
        """prev_row is accepted for interface parity with the other CFD
        strategies (CfdBacktestEngine always passes it) but unused --
        like DonchianBreakoutStrategy, every decision here is fully
        determined by the current bar (its hour, and its close against
        that day's already-complete Asian range)."""
        price = row["close"]
        hour = int(row["_hour"])

        if in_position is not None:
            if hour >= self.session_close_hour:
                side = "long" if in_position == "long" else "short"
                action = Action.SELL if side == "long" else Action.BUY
                return Signal(symbol, action, price, reason=f"session close cutoff ({self.session_close_hour}:00 UTC)")
            return Signal(symbol, Action.HOLD, price, reason=f"holding {in_position}")

        if pd.isna(row["asian_high"]) or pd.isna(row["asian_low"]) or pd.isna(row["atr"]):
            return Signal(symbol, Action.HOLD, price, reason="warming up (no complete Asian range yet)")

        if not self._in_breakout_window(hour):
            return Signal(symbol, Action.HOLD, price, reason="outside the London breakout window")

        if price > row["asian_high"]:
            stop = price - self.atr_stop_mult * row["atr"]
            target = price + self.atr_target_mult * row["atr"]
            return Signal(symbol, Action.BUY, price, stop, target, "closed above the Asian session high")
        if price < row["asian_low"]:
            stop = price + self.atr_stop_mult * row["atr"]
            target = price - self.atr_target_mult * row["atr"]
            return Signal(symbol, Action.SELL, price, stop, target, "closed below the Asian session low")

        return Signal(symbol, Action.HOLD, price, reason="still inside the Asian range")

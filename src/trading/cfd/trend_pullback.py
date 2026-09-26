import pandas as pd

from trading.indicators import adx, atr, ema
from trading.strategy.base import Action, Signal


class TrendPullbackStrategy:
    """Trend-following pullback entry on H1 bars.

    Long: fast EMA > slow EMA, ADX confirms trend, prior close is at/below
    fast EMA (pullback), and current close reclaims fast EMA.
    Short: mirror image.

    This is structurally different from EmaCrossoverStrategy: it does not
    require a fresh trend crossover, so it can enter established trends on
    retracements. Parameters remain unvalidated until research gates pass.
    """

    def __init__(
        self,
        fast_span: int = 20,
        slow_span: int = 50,
        adx_window: int = 14,
        adx_threshold: float = 20.0,
        atr_window: int = 14,
        pullback_atr_tolerance: float = 0.5,
        atr_stop_mult: float = 2.0,
        atr_target_mult: float = 3.0,
    ):
        self.fast_span = fast_span
        self.slow_span = slow_span
        self.adx_window = adx_window
        self.adx_threshold = adx_threshold
        self.atr_window = atr_window
        self.pullback_atr_tolerance = pullback_atr_tolerance
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        df["fast_ema"] = ema(df["close"], self.fast_span)
        df["slow_ema"] = ema(df["close"], self.slow_span)
        df["adx"] = adx(df["high"], df["low"], df["close"], self.adx_window)
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        return df

    def signal_for_row(self, symbol: str, row: pd.Series, prev_row: pd.Series, in_position: str | None) -> Signal:
        price = row["close"]
        needed = ("fast_ema", "slow_ema", "adx", "atr")
        if any(c not in row.index or pd.isna(row[c]) for c in needed) or any(
            c not in prev_row.index or pd.isna(prev_row[c]) for c in needed
        ):
            return Signal(symbol, Action.HOLD, price, reason="warming up")

        long_trend = row["fast_ema"] > row["slow_ema"] and row["adx"] >= self.adx_threshold
        short_trend = row["fast_ema"] < row["slow_ema"] and row["adx"] >= self.adx_threshold

        if in_position == "long":
            if row["fast_ema"] < row["slow_ema"]:
                return Signal(symbol, Action.SELL, price, reason="trend reversed below slow EMA")
            return Signal(symbol, Action.HOLD, price, reason="holding long")
        if in_position == "short":
            if row["fast_ema"] > row["slow_ema"]:
                return Signal(symbol, Action.BUY, price, reason="trend reversed above slow EMA")
            return Signal(symbol, Action.HOLD, price, reason="holding short")

        tolerance = self.pullback_atr_tolerance * row["atr"]
        prev_near_or_below_fast = prev_row["close"] <= prev_row["fast_ema"] + tolerance
        prev_near_or_above_fast = prev_row["close"] >= prev_row["fast_ema"] - tolerance
        reclaimed_up = prev_row["close"] <= prev_row["fast_ema"] and price > row["fast_ema"]
        reclaimed_down = prev_row["close"] >= prev_row["fast_ema"] and price < row["fast_ema"]

        if long_trend and prev_near_or_below_fast and reclaimed_up:
            stop = price - self.atr_stop_mult * row["atr"]
            target = price + self.atr_target_mult * row["atr"]
            return Signal(symbol, Action.BUY, price, stop, target, "trend pullback reclaimed fast EMA")

        if short_trend and prev_near_or_above_fast and reclaimed_down:
            stop = price + self.atr_stop_mult * row["atr"]
            target = price - self.atr_target_mult * row["atr"]
            return Signal(symbol, Action.SELL, price, stop, target, "trend pullback lost fast EMA")

        return Signal(symbol, Action.HOLD, price, reason="no qualified trend pullback")

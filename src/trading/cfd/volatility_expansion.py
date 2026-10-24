import pandas as pd

from trading.indicators import atr, bollinger_bands, donchian_channel
from trading.strategy.base import Action, Signal


class VolatilityExpansionBreakoutStrategy:
    """Compression-to-expansion breakout candidate for CFD H1 bars.

    This is intentionally different from plain Donchian breakout. A new
    entry is allowed only when volatility was compressed relative to its
    own trailing history and the latest close then breaks a prior-price
    channel while ATR expands. The goal is to detect range -> expansion
    transitions rather than continuously trade an already-trending market.

    RESEARCH/CANDIDATE only until validated. No live/demo-account orders
    should be generated from this class unless it earns later lifecycle
    promotion.
    """

    def __init__(
        self,
        channel_window: int = 20,
        bb_window: int = 20,
        bb_std: float = 2.0,
        compression_lookback: int = 100,
        compression_quantile: float = 0.25,
        atr_window: int = 14,
        atr_expansion_mult: float = 1.10,
        atr_stop_mult: float = 2.0,
        atr_target_mult: float = 3.0,
    ):
        self.channel_window = channel_window
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.compression_lookback = compression_lookback
        self.compression_quantile = compression_quantile
        self.atr_window = atr_window
        self.atr_expansion_mult = atr_expansion_mult
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        upper, _, lower = bollinger_bands(df["close"], self.bb_window, self.bb_std)
        width = (upper - lower) / df["close"].replace(0, pd.NA)
        # Compression threshold uses only information available before the
        # current bar to avoid lookahead in both backtests and live runs.
        df["bb_width"] = width
        df["compression_threshold"] = width.shift(1).rolling(
            self.compression_lookback,
            min_periods=max(20, min(self.compression_lookback, 20)),
        ).quantile(self.compression_quantile)

        ch_high, ch_low = donchian_channel(df["high"], df["low"], self.channel_window)
        df["channel_high"] = ch_high
        df["channel_low"] = ch_low
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_window)
        df["atr_prev"] = df["atr"].shift(1)
        return df

    def signal_for_row(self, symbol: str, row: pd.Series, prev_row: pd.Series, in_position: str | None) -> Signal:
        price = row["close"]
        needed = ("bb_width", "compression_threshold", "channel_high", "channel_low", "atr", "atr_prev")
        if any(c not in row.index or pd.isna(row[c]) for c in needed):
            return Signal(symbol, Action.HOLD, price, reason="warming up")

        if in_position == "long":
            if price < row["channel_low"]:
                return Signal(symbol, Action.SELL, price, reason="failed expansion: broke below channel")
            return Signal(symbol, Action.HOLD, price, reason="holding long")

        if in_position == "short":
            if price > row["channel_high"]:
                return Signal(symbol, Action.BUY, price, reason="failed expansion: broke above channel")
            return Signal(symbol, Action.HOLD, price, reason="holding short")

        # Require the immediately preceding bar to be compressed, not the
        # breakout bar itself. Then require ATR expansion on the breakout.
        prev_compressed = (
            "bb_width" in prev_row.index
            and "compression_threshold" in prev_row.index
            and not pd.isna(prev_row["bb_width"])
            and not pd.isna(prev_row["compression_threshold"])
            and prev_row["bb_width"] <= prev_row["compression_threshold"]
        )
        atr_expanding = row["atr_prev"] > 0 and row["atr"] >= row["atr_prev"] * self.atr_expansion_mult

        if not prev_compressed:
            return Signal(symbol, Action.HOLD, price, reason="no prior volatility compression")
        if not atr_expanding:
            return Signal(symbol, Action.HOLD, price, reason="breakout without ATR expansion")

        if price > row["channel_high"]:
            stop = price - self.atr_stop_mult * row["atr"]
            target = price + self.atr_target_mult * row["atr"]
            return Signal(symbol, Action.BUY, price, stop, target, "compression breakout with ATR expansion")
        if price < row["channel_low"]:
            stop = price + self.atr_stop_mult * row["atr"]
            target = price - self.atr_target_mult * row["atr"]
            return Signal(symbol, Action.SELL, price, stop, target, "compression breakdown with ATR expansion")

        return Signal(symbol, Action.HOLD, price, reason="compressed but no channel breakout")

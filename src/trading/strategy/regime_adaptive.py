import pandas as pd

from trading.regime import compute_market_regime
from trading.strategy.base import Signal
from trading.strategy.breakout import BreakoutStrategy
from trading.strategy.macd_trend import MacdTrendStrategy
from trading.strategy.mean_reversion import MeanReversionStrategy


class RegimeAdaptiveStrategy:
    """Switches which sub-strategy trades based on the broad market's
    regime, using a reference symbol (SPY by default) as a stand-in for
    "the market" so every symbol is judged against the same regime rather
    than its own idiosyncratic trend.

    The mapping is based on a backtest comparing all strategies across
    2020-2026:
      - bull    -> BreakoutStrategy (best risk-adjusted trend-following)
      - bear    -> MeanReversionStrategy (the only strategy that didn't
                   lose money in the 2022 bear market)
      - neutral -> MacdTrendStrategy (a more conservative, trend-filtered
                   momentum play, for turning points where neither extreme
                   applies)
    """

    def __init__(
        self,
        regime_bars: pd.DataFrame,
        sma_window: int = 200,
        slope_lookback: int = 20,
        bull_strategy=None,
        bear_strategy=None,
        neutral_strategy=None,
    ):
        self.regime_series = compute_market_regime(regime_bars, sma_window, slope_lookback)
        self.bull_strategy = bull_strategy or BreakoutStrategy()
        self.bear_strategy = bear_strategy or MeanReversionStrategy()
        self.neutral_strategy = neutral_strategy or MacdTrendStrategy()

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        df = self.bull_strategy.prepare(bars)
        df = self.bear_strategy.prepare(df)
        df = self.neutral_strategy.prepare(df)
        df["regime"] = self.regime_series.reindex(df.index).ffill().fillna("neutral")
        return df

    def signal_for_row(self, symbol: str, row: pd.Series, in_position: bool) -> Signal:
        regime = row["regime"]
        if regime == "bull":
            return self.bull_strategy.signal_for_row(symbol, row, in_position)
        if regime == "bear":
            return self.bear_strategy.signal_for_row(symbol, row, in_position)
        return self.neutral_strategy.signal_for_row(symbol, row, in_position)

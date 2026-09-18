import pandas as pd

from trading.indicators import sma


def compute_market_regime(
    reference_bars: pd.DataFrame, sma_window: int = 200, slope_lookback: int = 20
) -> pd.Series:
    """Classifies each date as "bull", "bear", or "neutral" from a reference
    symbol's price action (e.g. SPY, as a stand-in for "the market"):

      - bull:    price above its long moving average, and that average is
                 still rising
      - bear:    price below its long moving average, and that average is
                 still falling
      - neutral: anything else -- a turning point, or still warming up

    Used to pick which sub-strategy governs trading on a given date.
    """
    close = reference_bars["close"]
    trend = sma(close, sma_window)
    slope = trend - trend.shift(slope_lookback)

    regime = pd.Series("neutral", index=close.index)
    regime[(close > trend) & (slope > 0)] = "bull"
    regime[(close < trend) & (slope < 0)] = "bear"
    return regime

import numpy as np
import pandas as pd

from trading.regime import compute_market_regime


def _bars(close_values):
    dates = pd.date_range("2023-01-01", periods=len(close_values), freq="B")
    return pd.DataFrame({"close": pd.Series(close_values, index=dates)})


def test_steady_uptrend_classified_as_bull():
    close = np.linspace(100, 300, 260)
    regime = compute_market_regime(_bars(close), sma_window=200, slope_lookback=20)
    assert regime.iloc[-1] == "bull"


def test_steady_downtrend_classified_as_bear():
    close = np.linspace(300, 50, 260)
    regime = compute_market_regime(_bars(close), sma_window=200, slope_lookback=20)
    assert regime.iloc[-1] == "bear"


def test_warmup_period_is_neutral():
    close = np.linspace(100, 110, 50)  # far fewer bars than sma_window
    regime = compute_market_regime(_bars(close), sma_window=200, slope_lookback=20)
    assert regime.iloc[0] == "neutral"
    assert regime.iloc[-1] == "neutral"

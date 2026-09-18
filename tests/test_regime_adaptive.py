import numpy as np
import pandas as pd

from trading.strategy.base import Action
from trading.strategy.mean_reversion import MeanReversionStrategy
from trading.strategy.regime_adaptive import RegimeAdaptiveStrategy


def _bars(close_values):
    dates = pd.date_range("2020-01-01", periods=len(close_values), freq="B")
    close = pd.Series(close_values, index=dates)
    high = close + 1
    low = close - 1
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": 1_000_000}, index=dates
    )


def test_prepare_adds_regime_and_all_sub_strategy_columns():
    n = 260
    regime_bars = _bars(np.linspace(100, 300, n))
    strategy = RegimeAdaptiveStrategy(regime_bars=regime_bars)
    df = strategy.prepare(_bars(np.linspace(50, 150, n)))
    for col in ("regime", "entry_high", "exit_low", "bb_upper", "bb_mid", "macd", "sma_trend"):
        assert col in df.columns


def test_delegates_to_bull_strategy_in_uptrend():
    n = 260
    regime_bars = _bars(np.linspace(100, 300, n))
    strategy = RegimeAdaptiveStrategy(regime_bars=regime_bars)

    symbol_bars = _bars(np.concatenate([np.full(n - 1, 100.0), [140.0]]))  # breakout on last bar
    df = strategy.prepare(symbol_bars)
    row = df.iloc[-1]

    assert row["regime"] == "bull"
    signal = strategy.signal_for_row("TEST", row, in_position=False)
    assert signal.action == Action.BUY


def test_delegates_to_bear_strategy_in_downtrend():
    n = 260
    regime_bars = _bars(np.linspace(300, 50, n))
    strategy = RegimeAdaptiveStrategy(
        regime_bars=regime_bars, bear_strategy=MeanReversionStrategy(rsi_oversold=100)
    )

    flat = np.full(n - 5, 100.0)
    dip = np.linspace(100, 80, 5)
    symbol_bars = _bars(np.concatenate([flat, dip]))
    df = strategy.prepare(symbol_bars)
    row = df.iloc[-1]

    assert row["regime"] == "bear"
    signal = strategy.signal_for_row("TEST", row, in_position=False)
    assert signal.action == Action.BUY

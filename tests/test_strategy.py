import numpy as np
import pandas as pd

from trading.strategy.base import Action
from trading.strategy.trend_momentum import TrendMomentumStrategy


def _uptrend_bars(n=80):
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = pd.Series(np.linspace(100, 160, n), index=dates)
    high = close + 1
    low = close - 1
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": 1_000_000}, index=dates
    )


def test_prepare_adds_expected_columns():
    strategy = TrendMomentumStrategy()
    df = strategy.prepare(_uptrend_bars())
    for col in ("ema_fast", "ema_slow", "rsi", "atr", "trend_up"):
        assert col in df.columns


def test_buy_signal_in_clear_uptrend():
    strategy = TrendMomentumStrategy(rsi_low=0, rsi_high=100)
    df = strategy.prepare(_uptrend_bars())
    row = df.iloc[-1]
    signal = strategy.signal_for_row("TEST", row, in_position=False)
    assert signal.action == Action.BUY
    assert signal.stop_price < signal.price < signal.take_profit_price


def test_hold_signal_while_warming_up():
    strategy = TrendMomentumStrategy()
    df = strategy.prepare(_uptrend_bars())
    row = df.iloc[0]
    signal = strategy.signal_for_row("TEST", row, in_position=False)
    assert signal.action == Action.HOLD

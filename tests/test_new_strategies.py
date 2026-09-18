import numpy as np
import pandas as pd

from trading.strategy.base import Action
from trading.strategy.breakout import BreakoutStrategy
from trading.strategy.buy_and_hold import BuyAndHoldStrategy
from trading.strategy.macd_trend import MacdTrendStrategy
from trading.strategy.mean_reversion import MeanReversionStrategy


def _bars(close_values, n=None):
    n = n or len(close_values)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = pd.Series(close_values, index=dates)
    high = close + 1
    low = close - 1
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": 1_000_000}, index=dates
    )


def _flat_then_dip_bars(n=80):
    flat = np.full(n - 5, 100.0)
    dip = np.linspace(100, 80, 5)  # sharp drop -> oversold
    return _bars(np.concatenate([flat, dip]))


def _uptrend_bars(n=260):
    return _bars(np.linspace(50, 200, n))


def _new_high_bars(n=80):
    # flat range, then a decisive breakout above it on the last bar
    flat = np.full(n - 1, 100.0)
    return _bars(np.concatenate([flat, [130.0]]))


class TestMeanReversionStrategy:
    def test_buy_signal_on_oversold_dip(self):
        strategy = MeanReversionStrategy(rsi_oversold=100)  # loosen RSI filter for a deterministic test
        df = strategy.prepare(_flat_then_dip_bars())
        row = df.iloc[-1]
        signal = strategy.signal_for_row("TEST", row, in_position=False)
        assert signal.action == Action.BUY
        assert signal.stop_price < signal.price < signal.take_profit_price

    def test_hold_while_warming_up(self):
        strategy = MeanReversionStrategy()
        df = strategy.prepare(_flat_then_dip_bars())
        signal = strategy.signal_for_row("TEST", df.iloc[0], in_position=False)
        assert signal.action == Action.HOLD


class TestMacdTrendStrategy:
    def test_prepare_adds_expected_columns(self):
        strategy = MacdTrendStrategy(trend_window=50)
        df = strategy.prepare(_uptrend_bars())
        for col in ("macd", "macd_signal", "sma_trend", "atr", "macd_above_signal"):
            assert col in df.columns

    def test_buy_signal_in_strong_uptrend(self):
        strategy = MacdTrendStrategy(trend_window=50)
        df = strategy.prepare(_uptrend_bars())
        row = df.iloc[-1]
        signal = strategy.signal_for_row("TEST", row, in_position=False)
        assert signal.action == Action.BUY
        assert signal.stop_price < signal.price < signal.take_profit_price


class TestBreakoutStrategy:
    def test_buy_signal_on_new_high_breakout(self):
        strategy = BreakoutStrategy(entry_window=20, exit_window=10)
        df = strategy.prepare(_new_high_bars())
        row = df.iloc[-1]
        signal = strategy.signal_for_row("TEST", row, in_position=False)
        assert signal.action == Action.BUY

    def test_hold_without_breakout(self):
        strategy = BreakoutStrategy(entry_window=20, exit_window=10)
        df = strategy.prepare(_bars(np.full(80, 100.0)))
        row = df.iloc[-1]
        signal = strategy.signal_for_row("TEST", row, in_position=False)
        assert signal.action == Action.HOLD


class TestBuyAndHoldStrategy:
    def test_buys_on_first_valid_bar_and_then_holds(self):
        strategy = BuyAndHoldStrategy()
        df = strategy.prepare(_bars([100.0, 101.0, 99.0]))
        first_signal = strategy.signal_for_row("TEST", df.iloc[0], in_position=False)
        assert first_signal.action == Action.BUY

        held_signal = strategy.signal_for_row("TEST", df.iloc[1], in_position=True)
        assert held_signal.action == Action.HOLD

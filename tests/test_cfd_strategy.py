import pandas as pd

from trading.cfd.strategy import EmaCrossoverStrategy
from trading.strategy.base import Action


def _row(fast_ema, slow_ema, atr, close=100.0):
    return pd.Series({"close": close, "fast_ema": fast_ema, "slow_ema": slow_ema, "atr": atr})


def test_flat_bullish_crossover_opens_long_with_stop_below_and_target_above():
    strategy = EmaCrossoverStrategy(atr_stop_mult=1.5, atr_target_mult=2.5)
    prev_row = _row(fast_ema=99, slow_ema=100, atr=2)
    row = _row(fast_ema=101, slow_ema=100, atr=2)
    signal = strategy.signal_for_row("EUR_USD", row, prev_row, in_position=None)
    assert signal.action == Action.BUY
    assert signal.stop_price == 100.0 - 1.5 * 2
    assert signal.take_profit_price == 100.0 + 2.5 * 2


def test_flat_bearish_crossover_opens_short_with_stop_above_and_target_below():
    strategy = EmaCrossoverStrategy(atr_stop_mult=1.5, atr_target_mult=2.5)
    prev_row = _row(fast_ema=101, slow_ema=100, atr=2)
    row = _row(fast_ema=99, slow_ema=100, atr=2)
    signal = strategy.signal_for_row("EUR_USD", row, prev_row, in_position=None)
    assert signal.action == Action.SELL
    assert signal.stop_price == 100.0 + 1.5 * 2
    assert signal.take_profit_price == 100.0 - 2.5 * 2


def test_long_position_closes_on_bearish_crossover():
    strategy = EmaCrossoverStrategy()
    prev_row = _row(fast_ema=101, slow_ema=100, atr=2)
    row = _row(fast_ema=99, slow_ema=100, atr=2)
    signal = strategy.signal_for_row("EUR_USD", row, prev_row, in_position="long")
    assert signal.action == Action.SELL


def test_short_position_covers_on_bullish_crossover():
    strategy = EmaCrossoverStrategy()
    prev_row = _row(fast_ema=99, slow_ema=100, atr=2)
    row = _row(fast_ema=101, slow_ema=100, atr=2)
    signal = strategy.signal_for_row("EUR_USD", row, prev_row, in_position="short")
    assert signal.action == Action.BUY


def test_no_crossover_holds():
    strategy = EmaCrossoverStrategy()
    prev_row = _row(fast_ema=101, slow_ema=100, atr=2)
    row = _row(fast_ema=102, slow_ema=100, atr=2)
    signal = strategy.signal_for_row("EUR_USD", row, prev_row, in_position=None)
    assert signal.action == Action.HOLD


def test_warming_up_holds_when_indicators_are_nan():
    strategy = EmaCrossoverStrategy()
    prev_row = _row(fast_ema=float("nan"), slow_ema=100, atr=2)
    row = _row(fast_ema=101, slow_ema=100, atr=2)
    signal = strategy.signal_for_row("EUR_USD", row, prev_row, in_position=None)
    assert signal.action == Action.HOLD
    assert signal.reason == "warming up"

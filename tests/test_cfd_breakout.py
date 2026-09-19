import pandas as pd

from trading.cfd.breakout import DonchianBreakoutStrategy
from trading.strategy.base import Action


def _row(entry_high, entry_low, exit_high, exit_low, atr, close):
    return pd.Series(
        {
            "close": close,
            "entry_high": entry_high,
            "entry_low": entry_low,
            "exit_high": exit_high,
            "exit_low": exit_low,
            "atr": atr,
        }
    )


def test_breaks_above_entry_high_opens_long_with_stop_below_and_target_above():
    strategy = DonchianBreakoutStrategy(atr_stop_mult=2.0, atr_target_mult=3.0)
    row = _row(entry_high=100, entry_low=90, exit_high=98, exit_low=92, atr=2, close=101)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.BUY
    assert signal.stop_price == 101 - 2.0 * 2
    assert signal.take_profit_price == 101 + 3.0 * 2


def test_breaks_below_entry_low_opens_short_with_stop_above_and_target_below():
    strategy = DonchianBreakoutStrategy(atr_stop_mult=2.0, atr_target_mult=3.0)
    row = _row(entry_high=100, entry_low=90, exit_high=98, exit_low=92, atr=2, close=89)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.SELL
    assert signal.stop_price == 89 + 2.0 * 2
    assert signal.take_profit_price == 89 - 3.0 * 2


def test_no_breakout_holds_flat():
    strategy = DonchianBreakoutStrategy()
    row = _row(entry_high=100, entry_low=90, exit_high=98, exit_low=92, atr=2, close=95)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD


def test_long_position_closes_on_exit_channel_break():
    strategy = DonchianBreakoutStrategy()
    row = _row(entry_high=100, entry_low=90, exit_high=98, exit_low=92, atr=2, close=91)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="long")
    assert signal.action == Action.SELL


def test_long_position_holds_above_exit_channel():
    strategy = DonchianBreakoutStrategy()
    row = _row(entry_high=100, entry_low=90, exit_high=98, exit_low=92, atr=2, close=95)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="long")
    assert signal.action == Action.HOLD


def test_short_position_covers_on_exit_channel_break():
    strategy = DonchianBreakoutStrategy()
    row = _row(entry_high=100, entry_low=90, exit_high=98, exit_low=92, atr=2, close=99)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="short")
    assert signal.action == Action.BUY


def test_short_position_holds_below_exit_channel():
    strategy = DonchianBreakoutStrategy()
    row = _row(entry_high=100, entry_low=90, exit_high=98, exit_low=92, atr=2, close=95)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="short")
    assert signal.action == Action.HOLD


def test_warming_up_holds_when_indicators_are_nan():
    strategy = DonchianBreakoutStrategy()
    row = _row(entry_high=float("nan"), entry_low=90, exit_high=98, exit_low=92, atr=2, close=101)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD
    assert signal.reason == "warming up"

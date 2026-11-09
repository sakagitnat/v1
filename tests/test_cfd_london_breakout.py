import pandas as pd
import pytest

from trading.cfd.london_breakout import LondonBreakoutStrategy
from trading.strategy.base import Action


def _row(hour, asian_high, asian_low, atr, close):
    return pd.Series({"_hour": hour, "asian_high": asian_high, "asian_low": asian_low, "atr": atr, "close": close})


def test_constructor_rejects_out_of_order_hours():
    with pytest.raises(ValueError):
        LondonBreakoutStrategy(asian_start_hour=7, asian_end_hour=0)  # start must be before end
    with pytest.raises(ValueError):
        LondonBreakoutStrategy(asian_end_hour=10, breakout_end_hour=7)  # breakout window before Asian range ends


def test_close_above_asian_high_inside_breakout_window_opens_long():
    strategy = LondonBreakoutStrategy(asian_end_hour=7, breakout_end_hour=10, atr_stop_mult=1.5, atr_target_mult=3.0)
    row = _row(hour=8, asian_high=100, asian_low=95, atr=2, close=101)
    signal = strategy.signal_for_row("frxEURUSD", row, row, in_position=None)
    assert signal.action == Action.BUY
    assert signal.stop_price == 101 - 1.5 * 2
    assert signal.take_profit_price == 101 + 3.0 * 2


def test_close_below_asian_low_inside_breakout_window_opens_short():
    strategy = LondonBreakoutStrategy(asian_end_hour=7, breakout_end_hour=10, atr_stop_mult=1.5, atr_target_mult=3.0)
    row = _row(hour=9, asian_high=100, asian_low=95, atr=2, close=94)
    signal = strategy.signal_for_row("frxEURUSD", row, row, in_position=None)
    assert signal.action == Action.SELL
    assert signal.stop_price == 94 + 1.5 * 2
    assert signal.take_profit_price == 94 - 3.0 * 2


def test_breakout_outside_the_window_is_ignored():
    # Same break above asian_high as the long-entry test, but at hour 14 --
    # well past breakout_end_hour=10 -- must NOT open a new position.
    strategy = LondonBreakoutStrategy(asian_end_hour=7, breakout_end_hour=10)
    row = _row(hour=14, asian_high=100, asian_low=95, atr=2, close=105)
    signal = strategy.signal_for_row("frxEURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD


def test_price_inside_asian_range_during_window_holds_flat():
    strategy = LondonBreakoutStrategy(asian_end_hour=7, breakout_end_hour=10)
    row = _row(hour=8, asian_high=100, asian_low=95, atr=2, close=97)
    signal = strategy.signal_for_row("frxEURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD


def test_warming_up_with_no_asian_range_yet_holds_flat():
    strategy = LondonBreakoutStrategy(asian_end_hour=7, breakout_end_hour=10)
    row = _row(hour=8, asian_high=float("nan"), asian_low=float("nan"), atr=2, close=101)
    signal = strategy.signal_for_row("frxEURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD


def test_open_long_position_holds_before_session_close_hour():
    strategy = LondonBreakoutStrategy(session_close_hour=20)
    row = _row(hour=15, asian_high=100, asian_low=95, atr=2, close=103)
    signal = strategy.signal_for_row("frxEURUSD", row, row, in_position="long")
    assert signal.action == Action.HOLD


def test_open_long_position_force_closes_at_session_close_hour():
    strategy = LondonBreakoutStrategy(session_close_hour=20)
    row = _row(hour=20, asian_high=100, asian_low=95, atr=2, close=103)
    signal = strategy.signal_for_row("frxEURUSD", row, row, in_position="long")
    assert signal.action == Action.SELL


def test_open_short_position_force_covers_at_session_close_hour():
    strategy = LondonBreakoutStrategy(session_close_hour=20)
    row = _row(hour=20, asian_high=100, asian_low=95, atr=2, close=90)
    signal = strategy.signal_for_row("frxEURUSD", row, row, in_position="short")
    assert signal.action == Action.BUY


def test_prepare_computes_each_days_asian_range_and_forward_fills_it():
    strategy = LondonBreakoutStrategy(asian_start_hour=0, asian_end_hour=7)
    idx = pd.date_range("2026-01-05", periods=24, freq="1h", tz="UTC")  # one full day, hourly
    bars = pd.DataFrame(
        {
            "open": range(24),
            "high": [110 if h < 7 else 100 for h in range(24)],  # Asian session (0-6) has the day's real high
            "low": [90 if h < 7 else 95 for h in range(24)],  # and the real low
            "close": range(24),
        },
        index=idx,
    )
    out = strategy.prepare(bars)

    # Every bar that day, including ones before/after the Asian window itself,
    # should see the same completed Asian high/low for the day.
    assert (out["asian_high"] == 110).all()
    assert (out["asian_low"] == 90).all()


def test_prepare_keeps_different_days_asian_ranges_independent():
    strategy = LondonBreakoutStrategy(asian_start_hour=0, asian_end_hour=7)
    idx = pd.date_range("2026-01-05", periods=48, freq="1h", tz="UTC")  # two days
    highs = [110 if h < 7 else 100 for h in range(24)] + [120 if h < 7 else 100 for h in range(24)]
    lows = [90 if h < 7 else 95 for h in range(24)] + [80 if h < 7 else 95 for h in range(24)]
    bars = pd.DataFrame({"open": range(48), "high": highs, "low": lows, "close": range(48)}, index=idx)
    out = strategy.prepare(bars)

    assert out["asian_high"].iloc[12] == 110  # day 1
    assert out["asian_high"].iloc[36] == 120  # day 2, independent of day 1's range
    assert out["asian_low"].iloc[12] == 90
    assert out["asian_low"].iloc[36] == 80

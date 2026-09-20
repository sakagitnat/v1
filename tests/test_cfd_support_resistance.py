import pandas as pd

from trading.cfd.support_resistance import SupportResistanceReversionStrategy
from trading.strategy.base import Action


def _row(support, resistance, atr_value, low, high, close):
    return pd.Series({"close": close, "low": low, "high": high, "support": support, "resistance": resistance, "atr": atr_value})


def test_flat_low_touches_support_opens_long_with_atr_stop_and_target():
    strategy = SupportResistanceReversionStrategy(atr_stop_mult=1.5, atr_target_mult=2.5, touch_threshold_pct=0.001)
    row = _row(support=100, resistance=110, atr_value=2, low=100, high=105, close=101)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.BUY
    assert signal.stop_price == 100 - 1.5 * 2
    assert signal.take_profit_price == 101 + 2.5 * 2


def test_flat_high_touches_resistance_opens_short_with_atr_stop_and_target():
    strategy = SupportResistanceReversionStrategy(atr_stop_mult=1.5, atr_target_mult=2.5, touch_threshold_pct=0.001)
    row = _row(support=90, resistance=110, atr_value=2, low=105, high=110, close=109)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.SELL
    assert signal.stop_price == 110 + 1.5 * 2
    assert signal.take_profit_price == 109 - 2.5 * 2


def test_flat_low_far_below_stale_support_does_not_open_long():
    # Regression test: a one-sided check (low <= support*(1+pct)) is
    # also true for a low far BELOW a broken support, not just a
    # genuine touch -- this is what caused a live grid search to come
    # back with multi-million-percent CAGR (pathological re-entry on
    # every bar while price sat below a stale level). The fix requires
    # the low to land IN the tolerance band around support, so a price
    # that has clearly broken through and kept falling must HOLD, not
    # BUY.
    strategy = SupportResistanceReversionStrategy(touch_threshold_pct=0.001)
    row = _row(support=100, resistance=110, atr_value=2, low=50, high=51, close=50.5)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD


def test_flat_high_far_above_stale_resistance_does_not_open_short():
    strategy = SupportResistanceReversionStrategy(touch_threshold_pct=0.001)
    row = _row(support=90, resistance=110, atr_value=2, low=149, high=150, close=149.5)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD


def test_flat_no_touch_holds():
    strategy = SupportResistanceReversionStrategy()
    row = _row(support=90, resistance=110, atr_value=2, low=99, high=101, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD
    assert signal.reason == "no support/resistance touch"


def test_touch_threshold_allows_a_near_miss_within_tolerance():
    strategy = SupportResistanceReversionStrategy(touch_threshold_pct=0.01)
    row = _row(support=100, resistance=110, atr_value=2, low=100.5, high=105, close=101)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.BUY


def test_touch_threshold_rejects_a_miss_outside_tolerance():
    strategy = SupportResistanceReversionStrategy(touch_threshold_pct=0.0001)
    row = _row(support=100, resistance=110, atr_value=2, low=100.5, high=105, close=101)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD


def test_long_position_closes_when_price_reaches_midline():
    strategy = SupportResistanceReversionStrategy()
    row = _row(support=100, resistance=110, atr_value=2, low=104, high=106, close=105)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="long")
    assert signal.action == Action.SELL
    assert signal.reason == "reverted to support/resistance midline (close long)"


def test_long_position_holds_below_midline():
    strategy = SupportResistanceReversionStrategy()
    row = _row(support=100, resistance=110, atr_value=2, low=102, high=103, close=102)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="long")
    assert signal.action == Action.HOLD


def test_short_position_covers_when_price_reaches_midline():
    strategy = SupportResistanceReversionStrategy()
    row = _row(support=100, resistance=110, atr_value=2, low=104, high=106, close=105)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="short")
    assert signal.action == Action.BUY
    assert signal.reason == "reverted to support/resistance midline (cover short)"


def test_short_position_holds_above_midline():
    strategy = SupportResistanceReversionStrategy()
    row = _row(support=100, resistance=110, atr_value=2, low=107, high=108, close=107)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="short")
    assert signal.action == Action.HOLD


def test_warming_up_holds_when_indicator_is_nan():
    strategy = SupportResistanceReversionStrategy()
    row = _row(support=float("nan"), resistance=110, atr_value=2, low=100, high=105, close=101)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD
    assert signal.reason == "warming up"


def test_prepare_confirms_a_swing_low_only_after_the_pivot_window_lag():
    strategy = SupportResistanceReversionStrategy(pivot_window=2, atr_window=3)
    lows = [10.0] * 5 + [5.0] + [10.0] * 10
    highs = [12.0] * len(lows)
    closes = [11.0] * len(lows)
    bars = pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes})
    prepared = strategy.prepare(bars)

    pivot_index = 5  # where the swing low (5.0) sits
    confirm_index = pivot_index + strategy.pivot_window  # earliest index it can legitimately be known

    # Before confirmation, no future-leaked knowledge of the pivot low.
    assert prepared["support"].iloc[confirm_index - 1] != 5.0

    # From confirmation onward, the pivot low is reflected and persists (ffill).
    assert prepared["support"].iloc[confirm_index] == 5.0
    assert prepared["support"].iloc[-1] == 5.0


def test_prepare_adds_support_resistance_and_atr_columns():
    strategy = SupportResistanceReversionStrategy(pivot_window=2, atr_window=3)
    bars = pd.DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(20)],
            "high": [101.0 + i * 0.1 for i in range(20)],
            "low": [99.0 + i * 0.1 for i in range(20)],
            "close": [100.0 + i * 0.1 for i in range(20)],
        }
    )
    prepared = strategy.prepare(bars)
    for col in ("support", "resistance", "atr"):
        assert col in prepared.columns
    assert not pd.isna(prepared["atr"].iloc[-1])

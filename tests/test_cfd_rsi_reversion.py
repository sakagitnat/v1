import pandas as pd

from trading.cfd.rsi_reversion import RsiReversionStrategy
from trading.strategy.base import Action


def _row(rsi_value, adx_value, atr_value, close):
    return pd.Series({"close": close, "rsi": rsi_value, "adx": adx_value, "atr": atr_value})


def test_flat_oversold_opens_long_with_atr_stop_and_target():
    strategy = RsiReversionStrategy(atr_stop_mult=2.0, atr_target_mult=1.5)
    row = _row(rsi_value=25, adx_value=10, atr_value=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.BUY
    assert signal.stop_price == 96
    assert signal.take_profit_price == 103


def test_flat_overbought_opens_short_with_atr_stop_and_target():
    strategy = RsiReversionStrategy(atr_stop_mult=2.0, atr_target_mult=1.5)
    row = _row(rsi_value=75, adx_value=10, atr_value=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.SELL
    assert signal.stop_price == 104
    assert signal.take_profit_price == 97


def test_adx_gate_blocks_oversold_entry_in_trending_market():
    strategy = RsiReversionStrategy(adx_flat_threshold=15)
    row = _row(rsi_value=20, adx_value=16, atr_value=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD
    assert signal.reason == "ADX too high for flat-market RSI reversion"


def test_adx_gate_allows_entry_at_threshold_boundary():
    strategy = RsiReversionStrategy(adx_flat_threshold=15)
    row = _row(rsi_value=25, adx_value=15, atr_value=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.BUY


def test_non_extreme_rsi_holds_flat():
    strategy = RsiReversionStrategy()
    row = _row(rsi_value=50, adx_value=10, atr_value=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD
    assert signal.reason == "RSI not extreme enough for entry"


def test_long_closes_when_rsi_reaches_neutral():
    strategy = RsiReversionStrategy()
    row = _row(rsi_value=50, adx_value=30, atr_value=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="long")
    assert signal.action == Action.SELL
    assert signal.reason == "RSI reverted to neutral (close long)"


def test_long_holds_below_neutral_even_if_adx_is_high():
    strategy = RsiReversionStrategy()
    row = _row(rsi_value=49, adx_value=30, atr_value=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="long")
    assert signal.action == Action.HOLD


def test_short_covers_when_rsi_reaches_neutral():
    strategy = RsiReversionStrategy()
    row = _row(rsi_value=50, adx_value=30, atr_value=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="short")
    assert signal.action == Action.BUY
    assert signal.reason == "RSI reverted to neutral (cover short)"


def test_short_holds_above_neutral_even_if_adx_is_high():
    strategy = RsiReversionStrategy()
    row = _row(rsi_value=51, adx_value=30, atr_value=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="short")
    assert signal.action == Action.HOLD


def test_warming_up_holds_when_indicator_is_nan():
    strategy = RsiReversionStrategy()
    row = _row(rsi_value=25, adx_value=float("nan"), atr_value=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD
    assert signal.reason == "warming up"


def test_prepare_adds_rsi_adx_and_atr_columns():
    strategy = RsiReversionStrategy(rsi_window=5, adx_window=5, atr_window=5)
    bars = pd.DataFrame(
        {
            "open": [100 + i * 0.1 for i in range(30)],
            "high": [101 + i * 0.1 for i in range(30)],
            "low": [99 + i * 0.1 for i in range(30)],
            "close": [100 + i * 0.1 for i in range(30)],
        }
    )
    prepared = strategy.prepare(bars)
    for col in ("rsi", "adx", "atr"):
        assert col in prepared.columns
    assert not pd.isna(prepared["rsi"].iloc[-1])
    assert not pd.isna(prepared["adx"].iloc[-1])
    assert not pd.isna(prepared["atr"].iloc[-1])

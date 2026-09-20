import pandas as pd

from trading.cfd.mean_reversion import MeanReversionStrategy
from trading.strategy.base import Action


def _row(bb_upper, bb_mid, bb_lower, atr, close):
    return pd.Series(
        {
            "close": close,
            "bb_upper": bb_upper,
            "bb_mid": bb_mid,
            "bb_lower": bb_lower,
            "atr": atr,
        }
    )


def test_closes_below_lower_band_opens_long_with_stop_below_and_target_above():
    strategy = MeanReversionStrategy(atr_stop_mult=2.0, atr_target_mult=1.5)
    row = _row(bb_upper=110, bb_mid=100, bb_lower=90, atr=2, close=89)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.BUY
    assert signal.stop_price == 89 - 2.0 * 2
    assert signal.take_profit_price == 89 + 1.5 * 2


def test_closes_above_upper_band_opens_short_with_stop_above_and_target_below():
    strategy = MeanReversionStrategy(atr_stop_mult=2.0, atr_target_mult=1.5)
    row = _row(bb_upper=110, bb_mid=100, bb_lower=90, atr=2, close=111)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.SELL
    assert signal.stop_price == 111 + 2.0 * 2
    assert signal.take_profit_price == 111 - 1.5 * 2


def test_inside_bands_holds_flat():
    strategy = MeanReversionStrategy()
    row = _row(bb_upper=110, bb_mid=100, bb_lower=90, atr=2, close=101)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD
    assert signal.reason == "inside the bands, no extreme"


def test_long_position_closes_when_price_reverts_to_mid_band():
    strategy = MeanReversionStrategy()
    row = _row(bb_upper=110, bb_mid=100, bb_lower=90, atr=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="long")
    assert signal.action == Action.SELL
    assert signal.reason == "reverted to the mean (close long)"


def test_long_position_holds_below_mid_band():
    strategy = MeanReversionStrategy()
    row = _row(bb_upper=110, bb_mid=100, bb_lower=90, atr=2, close=95)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="long")
    assert signal.action == Action.HOLD
    assert signal.reason == "holding long, mean not reached yet"


def test_short_position_covers_when_price_reverts_to_mid_band():
    strategy = MeanReversionStrategy()
    row = _row(bb_upper=110, bb_mid=100, bb_lower=90, atr=2, close=100)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="short")
    assert signal.action == Action.BUY
    assert signal.reason == "reverted to the mean (cover short)"


def test_short_position_holds_above_mid_band():
    strategy = MeanReversionStrategy()
    row = _row(bb_upper=110, bb_mid=100, bb_lower=90, atr=2, close=105)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position="short")
    assert signal.action == Action.HOLD
    assert signal.reason == "holding short, mean not reached yet"


def test_warming_up_holds_when_indicators_are_nan():
    strategy = MeanReversionStrategy()
    row = _row(bb_upper=float("nan"), bb_mid=100, bb_lower=90, atr=2, close=89)
    signal = strategy.signal_for_row("EURUSD", row, row, in_position=None)
    assert signal.action == Action.HOLD
    assert signal.reason == "warming up"


def test_prepare_adds_band_and_atr_columns():
    strategy = MeanReversionStrategy(band_window=5, atr_window=5)
    bars = pd.DataFrame(
        {
            "open": [1.0] * 20,
            "high": [1.0 + 0.01 * i for i in range(20)],
            "low": [1.0 - 0.01 * i for i in range(20)],
            "close": [1.0 + 0.005 * i for i in range(20)],
        }
    )
    prepared = strategy.prepare(bars)
    for col in ("bb_upper", "bb_mid", "bb_lower", "atr"):
        assert col in prepared.columns
    # Enough bars past the warmup window for the indicators to be populated.
    assert not pd.isna(prepared["bb_mid"].iloc[-1])
    assert not pd.isna(prepared["atr"].iloc[-1])

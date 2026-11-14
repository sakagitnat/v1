import pandas as pd

from trading.cfd.meta_labeled_strategy import MetaLabeledStrategy
from trading.strategy.base import Action, Signal


class _FixedModel:
    """Stands in for a trained LogisticRegression -- always returns the
    same probability, so tests can pin exactly which side of
    `threshold` it falls on without depending on real training."""

    def __init__(self, probability):
        self.probability = probability

    def predict_proba(self, X):
        return [self.probability] * len(X)


class _ScriptedBaseStrategy:
    """Emits one fixed Signal regardless of input -- isolates
    MetaLabeledStrategy's own filtering logic from any real strategy's
    entry/exit rules."""

    def __init__(self, signal):
        self.signal = signal
        self.prepare_called_with = None

    def prepare(self, bars):
        self.prepare_called_with = bars
        return bars

    def signal_for_row(self, symbol, row, prev_row, in_position):
        return self.signal


def _row():
    return pd.Series({"close": 100.0, "adx": 25.0, "atr": 1.0, "fast_ema": 101.0, "slow_ema": 99.0})


def test_new_entry_below_threshold_is_suppressed_to_hold():
    base = _ScriptedBaseStrategy(Signal("EURUSD", Action.BUY, 100.0, stop_price=95.0, take_profit_price=105.0))
    wrapped = MetaLabeledStrategy(base, model=_FixedModel(0.3), threshold=0.5)

    signal = wrapped.signal_for_row("EURUSD", _row(), _row(), in_position=None)

    assert signal.action == Action.HOLD
    assert "meta-label filtered" in signal.reason


def test_new_entry_above_threshold_passes_through_unchanged():
    base_signal = Signal("EURUSD", Action.BUY, 100.0, stop_price=95.0, take_profit_price=105.0, reason="crossed up")
    base = _ScriptedBaseStrategy(base_signal)
    wrapped = MetaLabeledStrategy(base, model=_FixedModel(0.9), threshold=0.5)

    signal = wrapped.signal_for_row("EURUSD", _row(), _row(), in_position=None)

    assert signal is base_signal  # untouched, not even a copy


def test_exit_signal_is_never_filtered_even_below_threshold():
    # in_position="long" means this BUY/SELL from the base strategy is a
    # close/exit, not a new entry -- must pass through regardless of the
    # (deliberately low) meta-label probability.
    base_signal = Signal("EURUSD", Action.SELL, 100.0, reason="fast EMA crossed below slow EMA (close long)")
    base = _ScriptedBaseStrategy(base_signal)
    wrapped = MetaLabeledStrategy(base, model=_FixedModel(0.01), threshold=0.5)

    signal = wrapped.signal_for_row("EURUSD", _row(), _row(), in_position="long")

    assert signal is base_signal


def test_hold_signal_passes_through_without_querying_model():
    base_signal = Signal("EURUSD", Action.HOLD, 100.0, reason="no crossover")
    base = _ScriptedBaseStrategy(base_signal)

    class _ExplodingModel:
        def predict_proba(self, X):
            raise AssertionError("should never be called for a HOLD signal")

    wrapped = MetaLabeledStrategy(base, model=_ExplodingModel(), threshold=0.5)
    signal = wrapped.signal_for_row("EURUSD", _row(), _row(), in_position=None)

    assert signal is base_signal


def test_prepare_delegates_to_base_strategy():
    base = _ScriptedBaseStrategy(Signal("EURUSD", Action.HOLD, 100.0))
    wrapped = MetaLabeledStrategy(base, model=_FixedModel(0.5), threshold=0.5)
    bars = pd.DataFrame({"close": [1, 2, 3]})

    out = wrapped.prepare(bars)

    assert base.prepare_called_with is bars
    assert out is bars

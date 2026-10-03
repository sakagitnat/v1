import pandas as pd

from trading.cfd.volatility_expansion import VolatilityExpansionBreakoutStrategy
from trading.strategy.base import Action


def _row(close=101, channel_high=100, channel_low=90, atr=2.2, atr_prev=2.0, bb_width=0.03, threshold=0.02):
    return pd.Series({
        "close": close,
        "channel_high": channel_high,
        "channel_low": channel_low,
        "atr": atr,
        "atr_prev": atr_prev,
        "bb_width": bb_width,
        "compression_threshold": threshold,
    })


def test_long_requires_prior_compression_and_atr_expansion():
    s = VolatilityExpansionBreakoutStrategy(atr_expansion_mult=1.05)
    prev = _row(close=99, bb_width=0.01, threshold=0.02)
    row = _row(close=101, atr=2.2, atr_prev=2.0)
    sig = s.signal_for_row("EURUSD", row, prev, None)
    assert sig.action == Action.BUY
    assert sig.stop_price < sig.price < sig.take_profit_price


def test_short_requires_prior_compression_and_atr_expansion():
    s = VolatilityExpansionBreakoutStrategy(atr_expansion_mult=1.05)
    prev = _row(close=95, bb_width=0.01, threshold=0.02)
    row = _row(close=89, channel_high=100, channel_low=90, atr=2.2, atr_prev=2.0)
    sig = s.signal_for_row("EURUSD", row, prev, None)
    assert sig.action == Action.SELL
    assert sig.take_profit_price < sig.price < sig.stop_price


def test_no_trade_without_prior_compression():
    s = VolatilityExpansionBreakoutStrategy(atr_expansion_mult=1.05)
    prev = _row(bb_width=0.03, threshold=0.02)
    row = _row()
    sig = s.signal_for_row("EURUSD", row, prev, None)
    assert sig.action == Action.HOLD
    assert "compression" in sig.reason


def test_no_trade_without_atr_expansion():
    s = VolatilityExpansionBreakoutStrategy(atr_expansion_mult=1.10)
    prev = _row(bb_width=0.01, threshold=0.02)
    row = _row(atr=2.05, atr_prev=2.0)
    sig = s.signal_for_row("EURUSD", row, prev, None)
    assert sig.action == Action.HOLD
    assert "ATR expansion" in sig.reason


def test_no_trade_if_compressed_but_no_breakout():
    s = VolatilityExpansionBreakoutStrategy(atr_expansion_mult=1.05)
    prev = _row(bb_width=0.01, threshold=0.02)
    row = _row(close=95, channel_high=100, channel_low=90, atr=2.2, atr_prev=2.0)
    sig = s.signal_for_row("EURUSD", row, prev, None)
    assert sig.action == Action.HOLD
    assert "no channel breakout" in sig.reason

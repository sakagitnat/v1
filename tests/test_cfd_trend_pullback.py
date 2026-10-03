import pandas as pd

from trading.cfd.trend_pullback import TrendPullbackStrategy
from trading.strategy.base import Action


def _row(close, fast=100, slow=95, adx=30, atr=2):
    return pd.Series({"close": close, "fast_ema": fast, "slow_ema": slow, "adx": adx, "atr": atr})


def test_long_entry_on_reclaim_in_uptrend():
    s = TrendPullbackStrategy(adx_threshold=20)
    prev = _row(99, fast=100, slow=95)
    row = _row(101, fast=100.2, slow=95.5)
    sig = s.signal_for_row("EURUSD", row, prev, None)
    assert sig.action == Action.BUY
    assert sig.stop_price < sig.price < sig.take_profit_price


def test_short_entry_on_reclaim_in_downtrend():
    s = TrendPullbackStrategy(adx_threshold=20)
    prev = _row(101, fast=100, slow=105)
    row = _row(99, fast=99.8, slow=104.5)
    sig = s.signal_for_row("EURUSD", row, prev, None)
    assert sig.action == Action.SELL
    assert sig.take_profit_price < sig.price < sig.stop_price


def test_rejects_pullback_when_adx_is_too_low():
    s = TrendPullbackStrategy(adx_threshold=25)
    prev = _row(99, fast=100, slow=95, adx=20)
    row = _row(101, fast=100.2, slow=95.5, adx=20)
    sig = s.signal_for_row("EURUSD", row, prev, None)
    assert sig.action == Action.HOLD


def test_does_not_enter_without_reclaim():
    s = TrendPullbackStrategy()
    prev = _row(99, fast=100, slow=95)
    row = _row(99.5, fast=100.2, slow=95.5)
    sig = s.signal_for_row("EURUSD", row, prev, None)
    assert sig.action == Action.HOLD


def test_long_exits_when_trend_reverses():
    s = TrendPullbackStrategy()
    prev = _row(101, fast=100, slow=95)
    row = _row(98, fast=94, slow=96)
    sig = s.signal_for_row("EURUSD", row, prev, "long")
    assert sig.action == Action.SELL

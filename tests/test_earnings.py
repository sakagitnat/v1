import sys
import types

import pandas as pd

from trading.data.earnings import has_upcoming_earnings


class _FakeTicker:
    def __init__(self, dates_df):
        self._dates_df = dates_df

    def get_earnings_dates(self, limit=8):
        return self._dates_df


def _install_fake_yfinance(monkeypatch, ticker_factory):
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=ticker_factory))


def test_no_upcoming_earnings_when_data_is_empty(monkeypatch):
    _install_fake_yfinance(monkeypatch, lambda symbol: _FakeTicker(pd.DataFrame()))
    assert has_upcoming_earnings("SPY") is False


def test_no_upcoming_earnings_when_none_in_window(monkeypatch):
    now = pd.Timestamp.now(tz="America/New_York")
    dates = pd.DataFrame({"EPS Estimate": [1.0]}, index=pd.DatetimeIndex([now + pd.Timedelta(days=30)]))
    _install_fake_yfinance(monkeypatch, lambda symbol: _FakeTicker(dates))
    assert has_upcoming_earnings("AAPL", within_days=2) is False


def test_upcoming_earnings_within_window(monkeypatch):
    now = pd.Timestamp.now(tz="America/New_York")
    dates = pd.DataFrame({"EPS Estimate": [1.0]}, index=pd.DatetimeIndex([now + pd.Timedelta(days=1)]))
    _install_fake_yfinance(monkeypatch, lambda symbol: _FakeTicker(dates))
    assert has_upcoming_earnings("AAPL", within_days=2) is True


def test_past_earnings_outside_window_does_not_count(monkeypatch):
    now = pd.Timestamp.now(tz="America/New_York")
    dates = pd.DataFrame({"EPS Estimate": [1.0]}, index=pd.DatetimeIndex([now - pd.Timedelta(days=1)]))
    _install_fake_yfinance(monkeypatch, lambda symbol: _FakeTicker(dates))
    assert has_upcoming_earnings("AAPL", within_days=2) is False


def test_fails_open_when_ticker_lookup_raises(monkeypatch):
    def broken_ticker(symbol):
        raise RuntimeError("network down")

    _install_fake_yfinance(monkeypatch, broken_ticker)
    assert has_upcoming_earnings("AAPL") is False


def test_fails_open_when_dates_is_none(monkeypatch):
    _install_fake_yfinance(monkeypatch, lambda symbol: _FakeTicker(None))
    assert has_upcoming_earnings("AAPL") is False

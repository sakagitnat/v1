import pandas as pd

from trading.cfd.regime import RANGING, TRENDING, UNKNOWN, classify_regime


def _trending_bars(n=40):
    # A steady one-directional walk -- ADX should read a strong trend.
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    closes = [100.0 + i for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes}, index=idx)


def _ranging_bars(n=40):
    # Oscillates within a tight band -- ADX should read weak/no trend.
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    closes = [100.0 + (0.2 if i % 2 == 0 else -0.2) for i in range(n)]
    highs = [c + 0.1 for c in closes]
    lows = [c - 0.1 for c in closes]
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes}, index=idx)


def test_classifies_a_steady_trend_as_trending():
    assert classify_regime(_trending_bars()) == TRENDING


def test_classifies_a_tight_oscillation_as_ranging():
    assert classify_regime(_ranging_bars()) == RANGING


def test_returns_unknown_with_too_few_bars():
    assert classify_regime(_trending_bars(5), adx_window=14) == UNKNOWN


def test_trend_threshold_is_configurable():
    bars = _trending_bars()
    # An absurdly high threshold no real ADX reading could clear -- must
    # fall back to RANGING rather than TRENDING.
    assert classify_regime(bars, trend_threshold=999.0) == RANGING

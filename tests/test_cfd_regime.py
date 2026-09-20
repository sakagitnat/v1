import pandas as pd

from trading.cfd.regime import (
    RANGING,
    TRENDING,
    UNKNOWN,
    UNSTABLE,
    VOLATILITY_HIGH,
    VOLATILITY_LOW,
    VOLATILITY_NORMAL,
    VOLATILITY_UNKNOWN,
    classify_regime,
    classify_volatility,
)


def _trending_bars(n=40):
    # A steady one-directional walk -- ADX should read a strong trend.
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    closes = [100.0 + i for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes}, index=idx)


def _oscillating_bars(n, amplitude):
    closes = [100.0 + (amplitude if i % 2 == 0 else -amplitude) for i in range(n)]
    highs = [c + amplitude / 2 for c in closes]
    lows = [c - amplitude / 2 for c in closes]
    return closes, highs, lows


def _ranging_bars(n=40, amplitude=0.2):
    # Oscillates within a tight band -- ADX should read weak/no trend.
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    closes, highs, lows = _oscillating_bars(n, amplitude)
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes}, index=idx)


def _tail_volatility_bars(n_calm=45, n_tail=15, calm_amplitude=0.3, tail_amplitude=0.3):
    # A calm oscillating baseline, then a tail segment at a different
    # amplitude -- used to push the LATEST bar's ATR% above/below its own
    # recent median without changing the overall trend/no-trend read.
    idx = pd.date_range("2026-01-01", periods=n_calm + n_tail, freq="1h", tz="UTC")
    calm_closes, calm_highs, calm_lows = _oscillating_bars(n_calm, calm_amplitude)
    tail_closes, tail_highs, tail_lows = _oscillating_bars(n_tail, tail_amplitude)
    closes = calm_closes + tail_closes
    highs = calm_highs + tail_highs
    lows = calm_lows + tail_lows
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes}, index=idx)


def _unstable_bars(n_calm=40, n_volatile=15):
    # Calm oscillation, then violent alternating up/down swings -- huge
    # true range (ATR spikes) with the net directional bias cancelling
    # out each pair of bars, so ADX stays low (no clean trend) while
    # volatility spikes far above its own recent normal.
    calm_closes, calm_highs, calm_lows = _oscillating_bars(n_calm, 0.2)
    idx = pd.date_range("2026-01-01", periods=n_calm + n_volatile, freq="1h", tz="UTC")
    price = calm_closes[-1]
    vhigh, vlow, vclose = [], [], []
    for i in range(n_volatile):
        if i % 2 == 0:
            high, low, close = price + 10.0, price - 1.0, price + 0.2
        else:
            high, low, close = price + 1.0, price - 10.0, price - 0.2
        vhigh.append(high)
        vlow.append(low)
        vclose.append(close)
        price = close
    closes = calm_closes + vclose
    highs = calm_highs + vhigh
    lows = calm_lows + vlow
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


def test_classifies_a_volatility_spike_with_no_trend_as_unstable():
    # Distinct from ordinary RANGING: a whipsaw/choppy volatility spike,
    # not just calm no-direction price action.
    assert classify_regime(_unstable_bars()) == UNSTABLE


def test_a_volatile_but_trending_market_is_still_trending_not_unstable():
    # A strong trend justifies the risk a volatility spike alone
    # wouldn't -- UNSTABLE only overrides RANGING, never TRENDING.
    assert classify_regime(_trending_bars()) == TRENDING


def test_unstable_threshold_is_configurable():
    bars = _unstable_bars()
    # An absurdly high ratio no real spike could clear -- falls back to
    # ordinary RANGING instead of UNSTABLE.
    assert classify_regime(bars, unstable_volatility_ratio=999.0) == RANGING


def test_classify_volatility_reads_normal_for_steady_amplitude():
    assert classify_volatility(_ranging_bars(n=60, amplitude=0.3)) == VOLATILITY_NORMAL


def test_classify_volatility_reads_low_for_a_calmer_tail():
    bars = _tail_volatility_bars(calm_amplitude=0.3, tail_amplitude=0.05)
    assert classify_volatility(bars) == VOLATILITY_LOW


def test_classify_volatility_reads_high_for_a_more_active_tail():
    bars = _tail_volatility_bars(calm_amplitude=0.3, tail_amplitude=0.6)
    assert classify_volatility(bars) == VOLATILITY_HIGH


def test_classify_volatility_returns_unknown_with_too_little_history():
    assert classify_volatility(_ranging_bars(n=20), atr_window=14) == VOLATILITY_UNKNOWN

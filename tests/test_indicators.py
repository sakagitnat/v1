import numpy as np
import pandas as pd

from trading.indicators import adx, atr, bollinger_bands, donchian_channel, ema, macd, rsi, sma


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5])
    result = sma(s, window=2)
    assert result.iloc[-1] == 4.5


def test_ema_converges_to_constant():
    s = pd.Series([10.0] * 30)
    result = ema(s, span=5)
    assert abs(result.iloc[-1] - 10.0) < 1e-6


def test_rsi_all_gains_is_100():
    s = pd.Series(range(1, 30))
    result = rsi(s, window=14)
    assert result.iloc[-1] == 100


def test_atr_nonnegative():
    high = pd.Series([10, 11, 12, 11, 13])
    low = pd.Series([9, 9, 10, 9, 11])
    close = pd.Series([9.5, 10.5, 11, 10, 12])
    result = atr(high, low, close, window=3)
    assert (result.dropna() >= 0).all()


def test_macd_shapes_match():
    s = pd.Series(range(1, 60)).astype(float)
    macd_line, signal_line, hist = macd(s)
    assert len(macd_line) == len(signal_line) == len(hist) == len(s)


def test_bollinger_bands_ordering():
    s = pd.Series([10.0, 12.0, 9.0, 15.0, 8.0, 14.0, 11.0, 13.0, 9.5, 12.5] * 3)
    upper, mid, lower = bollinger_bands(s, window=10, num_std=2.0)
    valid = upper.notna()
    assert (upper[valid] >= mid[valid]).all()
    assert (mid[valid] >= lower[valid]).all()


def test_donchian_channel_excludes_current_bar():
    high = pd.Series([10.0] * 5 + [100.0])  # breakout only visible on the bar AFTER it happens
    low = pd.Series([9.0] * 6)
    upper, _ = donchian_channel(high, low, window=5)
    assert upper.iloc[5] == 10.0  # today's spike to 100 shouldn't count against itself


def test_adx_higher_for_a_strong_trend_than_a_flat_range():
    n = 60
    trend_close = pd.Series(np.linspace(100, 160, n))
    trend_high = trend_close + 0.5
    trend_low = trend_close - 0.5

    rng = np.random.default_rng(0)
    flat_close = pd.Series(100 + rng.normal(0, 0.3, n).cumsum() * 0 + rng.normal(0, 0.3, n))
    flat_high = flat_close + 0.5
    flat_low = flat_close - 0.5

    trend_adx = adx(trend_high, trend_low, trend_close, window=14).iloc[-1]
    flat_adx = adx(flat_high, flat_low, flat_close, window=14).iloc[-1]

    assert trend_adx > flat_adx
    assert trend_adx > 25  # Wilder's own rule-of-thumb threshold for "trending"


def test_adx_bounded_zero_to_hundred():
    high = pd.Series([10, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 17, 19, 20, 19, 21, 22])
    low = pd.Series([9, 9, 10, 9, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 17, 19, 20])
    close = pd.Series([9.5, 10.5, 11, 10, 12, 13, 12, 14, 15, 14, 16, 17, 16, 18, 19, 18, 20, 21])
    result = adx(high, low, close, window=5).dropna()
    assert (result >= 0).all() and (result <= 100).all()

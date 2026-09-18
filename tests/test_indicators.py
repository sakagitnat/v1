import pandas as pd

from trading.indicators import atr, ema, macd, rsi, sma


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

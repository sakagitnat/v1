import numpy as np
import pandas as pd

from trading.backtest.engine import BacktestEngine
from trading.strategy.trend_momentum import TrendMomentumStrategy


def _uptrend_then_flat_bars(n=150):
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = np.concatenate([np.linspace(100, 160, n // 2), np.full(n - n // 2, 160.0)])
    close = pd.Series(close, index=dates)
    high = close + 1
    low = close - 1
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": 1_000_000}, index=dates
    )


def test_backtest_produces_equity_curve_and_metrics():
    engine = BacktestEngine(strategy=TrendMomentumStrategy(rsi_low=0, rsi_high=100), starting_equity=100_000.0)
    result = engine.run({"TEST": _uptrend_then_flat_bars()})

    assert not result["equity_curve"].empty
    assert "cagr_pct" in result["metrics"]
    assert result["metrics"]["final_equity"] == round(float(result["equity_curve"].iloc[-1]), 2)


def test_backtest_handles_empty_input():
    engine = BacktestEngine(strategy=TrendMomentumStrategy())
    result = engine.run({})
    assert result["equity_curve"].empty
    assert result["trades"] == []

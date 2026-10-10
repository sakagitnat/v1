import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from optimize_cfd_strategy import (
    YFINANCE_INTERVAL_BY_GRANULARITY,
    _periods_per_year,
    _return_distribution_stats,
    fetch_history_yfinance,
    report_dsr,
    run_backtest_full,
)


def test_all_deriv_champion_granularities_are_mapped():
    # 1800 (M30) and 14400 (H4) used to be missing and silently fell back to
    # "1h" via .get(granularity_seconds, "1h") -- exactly the champion
    # timeframes this mapping now needs to support.
    assert YFINANCE_INTERVAL_BY_GRANULARITY[1800] == "30m"
    assert YFINANCE_INTERVAL_BY_GRANULARITY[3600] == "1h"
    assert YFINANCE_INTERVAL_BY_GRANULARITY[14400] == "4h"
    assert YFINANCE_INTERVAL_BY_GRANULARITY[86400] == "1d"


def _hourly_frame(n=8, start="2026-01-01"):
    idx = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"Open": range(n), "High": [x + 1 for x in range(n)], "Low": range(n), "Close": [x + 0.5 for x in range(n)]},
        index=idx,
    )


def test_4h_interval_fetches_native_1h_and_resamples(monkeypatch):
    calls = []

    def fake_download(ticker, period, interval, progress, auto_adjust):
        calls.append(interval)
        return _hourly_frame(n=8)

    import yfinance
    monkeypatch.setattr(yfinance, "download", fake_download)

    out = fetch_history_yfinance("frxEURUSD", "4h")

    assert calls == ["1h"]  # requested native 1h from yfinance, not "4h" (unsupported)
    assert len(out) == 2  # 8 hourly bars -> 2 four-hour bars
    assert list(out.columns) == ["open", "high", "low", "close"]


def test_30m_interval_fetches_native_30m_without_resampling(monkeypatch):
    calls = []

    def fake_download(ticker, period, interval, progress, auto_adjust):
        calls.append(interval)
        idx = pd.date_range("2026-01-01", periods=4, freq="30min", tz="UTC")
        return pd.DataFrame({"Open": [1, 2, 3, 4], "High": [1, 2, 3, 4], "Low": [1, 2, 3, 4], "Close": [1, 2, 3, 4]}, index=idx)

    import yfinance
    monkeypatch.setattr(yfinance, "download", fake_download)

    out = fetch_history_yfinance("frxEURUSD", "30m")

    assert calls == ["30m"]
    assert len(out) == 4


def _synthetic_bars(n=500, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    price = 100 + np.cumsum(rng.normal(0, 0.3, n))
    df = pd.DataFrame(
        {
            "open": price,
            "high": price + np.abs(rng.normal(0, 0.2, n)),
            "low": price - np.abs(rng.normal(0, 0.2, n)),
            "close": price,
        },
        index=idx,
    )
    return {"frxEURUSD": df}


def test_periods_per_year_matches_hourly_bar_spacing():
    full = run_backtest_full({}, _synthetic_bars())
    ppy = _periods_per_year(full["equity_curve"])
    # ~500 hourly bars spans ~20.8 days -- annualizing that out should land
    # close to the real "hours in a year" constant, not an arbitrary value.
    assert 7000 < ppy < 9500


def test_return_distribution_stats_shapes():
    full = run_backtest_full({}, _synthetic_bars())
    n_obs, skew, kurt = _return_distribution_stats(full["equity_curve"])
    assert n_obs == len(full["equity_curve"]) - 1  # pct_change() drops the first bar
    assert isinstance(skew, float) and isinstance(kurt, float)


def test_report_dsr_runs_end_to_end_without_error(capsys):
    # The integration this whole DSR addition exists for: a real
    # CfdBacktestEngine run feeding real equity-curve statistics through
    # to deflated_sharpe_ratio() without any shape/NaN surprises.
    bars = _synthetic_bars()
    report_dsr("synthetic baseline", {}, bars, sr_std_per_period=0.05, n_trials=243)
    out = capsys.readouterr().out
    assert "Deflated Sharpe Ratio" in out
    assert "243 trials searched" in out

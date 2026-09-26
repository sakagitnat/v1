import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from optimize_cfd_strategy import YFINANCE_INTERVAL_BY_GRANULARITY, fetch_history_yfinance


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

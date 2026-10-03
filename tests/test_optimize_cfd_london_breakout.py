import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from optimize_cfd_london_breakout import PARAM_GRID, report_dsr, run_backtest_full
from trading.cfd.london_breakout import LondonBreakoutStrategy


def _combos():
    keys = list(PARAM_GRID.keys())
    return [
        dict(zip(keys, values))
        for values in itertools.product(*PARAM_GRID.values())
        if values[0] < values[1] <= values[2]
    ]


def test_param_grid_combos_all_respect_the_window_ordering_constraint():
    combos = _combos()
    assert len(combos) > 0
    for c in combos:
        assert c["asian_end_hour"] < c["breakout_end_hour"] <= c["session_close_hour"]


def test_param_grid_combos_build_valid_strategy_instances():
    # Every combo the search will actually try must be a constructible
    # LondonBreakoutStrategy -- a combo that trips its own __init__
    # validation would silently never get backtested (or crash the grid
    # search outright) rather than being filtered out up front.
    for c in _combos():
        LondonBreakoutStrategy(**c)  # raises if the combo is invalid


def _synthetic_bars(n=2000, seed=11):
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


def test_run_backtest_full_runs_end_to_end_on_synthetic_data():
    full = run_backtest_full({}, _synthetic_bars(), LondonBreakoutStrategy)
    assert "equity_curve" in full and "trades" in full and "metrics" in full


def test_report_dsr_runs_end_to_end_without_error(capsys):
    bars = _synthetic_bars()
    report_dsr("synthetic baseline", {}, bars, sr_std_per_period=0.02, n_trials=243, strategy_cls=LondonBreakoutStrategy)
    out = capsys.readouterr().out
    assert "Deflated Sharpe Ratio" in out
    assert "243 trials searched" in out

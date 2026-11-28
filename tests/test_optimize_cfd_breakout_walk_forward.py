import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import optimize_cfd_breakout as ocb
from optimize_cfd_strategy import print_walk_forward_report, select_best_on_train
from trading.cfd.breakout import DonchianBreakoutStrategy
from trading.cfd.walk_forward import run_walk_forward


def _synthetic_bars(n=600, seed=23):
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


def test_combo_filter_requires_entry_window_wider_than_exit_window():
    assert ocb._combo_filter((30, 10, 2.5, 4.5)) is True
    assert ocb._combo_filter((10, 30, 2.5, 4.5)) is False


def test_select_best_on_train_works_with_breakout_grid_and_filter(monkeypatch):
    monkeypatch.setattr(ocb, "PARAM_GRID", {"entry_window": [30, 20], "exit_window": [10], "atr_stop_mult": [2.5], "atr_target_mult": [4.5]})
    kwargs, metrics = select_best_on_train(_synthetic_bars(), DonchianBreakoutStrategy, ocb.PARAM_GRID, ocb._combo_filter)
    assert isinstance(kwargs, dict)
    assert "num_trades" in metrics
    if kwargs:
        assert kwargs["entry_window"] > kwargs["exit_window"]


def test_walk_forward_report_runs_end_to_end(monkeypatch, capsys):
    monkeypatch.setattr(ocb, "PARAM_GRID", {"entry_window": [30], "exit_window": [10], "atr_stop_mult": [2.5], "atr_target_mult": [4.5]})
    bars = _synthetic_bars()

    def select_fn(train_bars):
        return select_best_on_train(train_bars, DonchianBreakoutStrategy, ocb.PARAM_GRID, ocb._combo_filter)

    report = run_walk_forward(bars, n_folds=2, select_fn=select_fn, evaluate_fn=lambda kw, b: ocb.run_backtest(kw, b))
    print_walk_forward_report(report)

    out = capsys.readouterr().out
    assert "Walk-forward validation: 2 folds" in out

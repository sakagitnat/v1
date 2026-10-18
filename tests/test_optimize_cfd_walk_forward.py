import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import optimize_cfd_strategy as ocs
from trading.cfd.walk_forward import run_walk_forward


def _synthetic_bars(n=600, seed=21):
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


def test_select_best_on_train_falls_back_to_baseline_when_nothing_qualifies(monkeypatch):
    # A grid with an impossibly strict MIN_TRADES-busting shape (tiny
    # data) should fall back to the untouched defaults, same contract
    # main()'s own "keep current defaults" path relies on.
    monkeypatch.setattr(ocs, "PARAM_GRID", {"fast_span": [10], "slow_span": [34], "atr_stop_mult": [2.0], "atr_target_mult": [2.0], "adx_threshold": [0]})
    tiny_bars = {"frxEURUSD": _synthetic_bars(n=5)["frxEURUSD"]}
    kwargs, metrics = ocs.select_best_on_train(tiny_bars)
    assert kwargs == {}
    assert "sharpe_ratio" in metrics


def test_select_best_on_train_returns_a_dict_and_metrics(monkeypatch):
    monkeypatch.setattr(ocs, "PARAM_GRID", {"fast_span": [10, 15], "slow_span": [34], "atr_stop_mult": [2.0], "atr_target_mult": [2.0], "adx_threshold": [0]})
    kwargs, metrics = ocs.select_best_on_train(_synthetic_bars())
    assert isinstance(kwargs, dict)
    assert "num_trades" in metrics


def test_walk_forward_report_prints_without_error(monkeypatch, capsys):
    monkeypatch.setattr(ocs, "PARAM_GRID", {"fast_span": [10], "slow_span": [34], "atr_stop_mult": [2.0], "atr_target_mult": [2.0], "adx_threshold": [0]})
    bars = _synthetic_bars()
    report = run_walk_forward(bars, n_folds=2, select_fn=ocs.select_best_on_train, evaluate_fn=ocs.run_backtest)

    ocs.print_walk_forward_report(report)

    out = capsys.readouterr().out
    assert "Walk-forward validation: 2 folds" in out
    assert "fraction of folds beating baseline" in out

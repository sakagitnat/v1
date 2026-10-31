import pandas as pd
import pytest

from trading.cfd.walk_forward import (
    FoldResult,
    WalkForwardReport,
    make_walk_forward_folds,
    run_walk_forward,
)


def _bars(n, start="2026-01-01"):
    idx = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"close": range(n)}, index=idx)


def test_n_folds_must_be_positive():
    with pytest.raises(ValueError):
        make_walk_forward_folds({"X": _bars(100)}, n_folds=0)


def test_single_fold_matches_a_simple_half_split():
    # n_folds=1 -> n_segments=2 -> fold 1's TRAIN is the first half,
    # TEST is the second half -- same shape as optimize_cfd_strategy.py's
    # own single TRAIN_FRACTION=0.5 split would produce.
    folds = make_walk_forward_folds({"X": _bars(100)}, n_folds=1)
    assert len(folds) == 1
    assert len(folds[0].train_bars["X"]) == 50
    assert len(folds[0].test_bars["X"]) == 50


def test_three_folds_have_expanding_train_windows():
    folds = make_walk_forward_folds({"X": _bars(100)}, n_folds=3)
    assert len(folds) == 3
    train_lengths = [len(f.train_bars["X"]) for f in folds]
    # Anchored/expanding: each fold's TRAIN strictly grows.
    assert train_lengths[0] < train_lengths[1] < train_lengths[2]


def test_folds_test_windows_are_sequential_and_non_overlapping():
    folds = make_walk_forward_folds({"X": _bars(100)}, n_folds=3)
    for f in folds:
        test_df = f.test_bars["X"]
        if test_df.empty:
            continue
        # Every row in this fold's TEST window comes strictly after
        # everything in its own TRAIN window.
        assert test_df.index[0] > f.train_bars["X"].index[-1]
    # Fold i+1's TRAIN fully contains fold i's TRAIN plus fold i's TEST.
    for i in range(len(folds) - 1):
        assert len(folds[i + 1].train_bars["X"]) == len(folds[i].train_bars["X"]) + len(folds[i].test_bars["X"])


def test_multi_instrument_bars_split_at_matching_fractional_positions():
    bars = {"A": _bars(100), "B": _bars(200)}
    folds = make_walk_forward_folds(bars, n_folds=1)
    # Both instruments split at the same fraction (50%), not the same
    # absolute row count.
    assert len(folds[0].train_bars["A"]) == 50
    assert len(folds[0].train_bars["B"]) == 100


def _dummy_metrics(cagr):
    return {"cagr_pct": cagr, "sharpe_ratio": cagr / 10, "max_drawdown_pct": -5.0, "num_trades": 10}


def test_run_walk_forward_builds_one_fold_result_per_fold():
    bars = {"X": _bars(200)}

    def select_fn(train_bars):
        return {"param": 1}, _dummy_metrics(10.0)

    def evaluate_fn(kwargs, test_bars):
        return _dummy_metrics(5.0)

    report = run_walk_forward(bars, n_folds=3, select_fn=select_fn, evaluate_fn=evaluate_fn)

    assert report.n_folds == 3
    assert all(isinstance(f, FoldResult) for f in report.folds)


def test_run_walk_forward_marks_beat_baseline_correctly():
    bars = {"X": _bars(200)}

    def select_fn(train_bars):
        return {"param": 1}, _dummy_metrics(10.0)

    def evaluate_fn(kwargs, test_bars):
        # The candidate (param=1) always beats baseline ({}); baseline
        # always scores worse.
        return _dummy_metrics(20.0) if kwargs else _dummy_metrics(5.0)

    report = run_walk_forward(bars, n_folds=2, select_fn=select_fn, evaluate_fn=evaluate_fn)

    assert all(f.beat_baseline for f in report.folds)


def test_report_aggregation_helpers():
    report = WalkForwardReport(
        folds=[
            FoldResult(1, {"p": 1}, _dummy_metrics(1), _dummy_metrics(10.0), True),
            FoldResult(2, {"p": 2}, _dummy_metrics(1), _dummy_metrics(20.0), False),
            FoldResult(3, {"p": 1}, _dummy_metrics(1), _dummy_metrics(-5.0), False),
        ]
    )

    assert report.mean_test("cagr_pct") == pytest.approx((10.0 + 20.0 - 5.0) / 3)
    assert report.worst_test("cagr_pct") == -5.0
    assert report.fraction_beating_baseline() == pytest.approx(1 / 3)
    assert report.param_stability() == {"p": {1, 2}}


def test_report_aggregation_helpers_empty_report():
    report = WalkForwardReport()
    assert report.n_folds == 0
    assert report.mean_test("cagr_pct") == 0.0
    assert report.worst_test("cagr_pct") == 0.0
    assert report.fraction_beating_baseline() == 0.0
    assert report.param_stability() == {}

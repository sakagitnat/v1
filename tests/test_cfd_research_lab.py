import pandas as pd

from trading.cfd import strategy_registry as reg
from trading.cfd.research_lab import (
    CandidateReport,
    evaluate_candidate,
    generate_candidate_params,
    register_if_passed,
)


def _use_tmp_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")


def test_generate_candidate_params_expands_full_grid():
    grid = {"a": [1, 2], "b": [10, 20]}
    combos = generate_candidate_params(grid)
    assert len(combos) == 4
    assert {"a": 1, "b": 10} in combos
    assert {"a": 2, "b": 20} in combos


def test_generate_candidate_params_applies_filter():
    grid = {"entry": [10, 20], "exit": [5, 15]}
    combos = generate_candidate_params(grid, filter_fn=lambda c: c["entry"] > c["exit"])
    assert all(c["entry"] > c["exit"] for c in combos)
    assert len(combos) == 3  # (10,5), (20,5), (20,15) -- not (10,15)


def _good_metrics(cagr=10.0, dd=-10.0, trades=50):
    return {"cagr_pct": cagr, "max_drawdown_pct": dd, "num_trades": trades, "sharpe_ratio": 1.0, "win_rate_pct": 55.0, "final_equity": 11000.0}


def _bars_with_marker(marker: str, n: int = 20) -> dict:
    # walk_forward's windowing slices real DataFrames by row -- a
    # constant "marker" column survives that slicing, so backtest_fn can
    # still tell a TRAIN call from a TEST (or walk-forward fold) call.
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {"marker": [marker] * n, "open": [1.0] * n, "high": [1.0] * n, "low": [1.0] * n, "close": [1.0] * n},
        index=idx,
    )
    return {"XAU": df}


def _make_backtest_fn(train_metrics, test_metrics, trades=None):
    trades = trades if trades is not None else [{"pnl": 10.0}] * 30 + [{"pnl": -5.0}] * 10

    def backtest_fn(params, bars):
        marker = bars["XAU"]["marker"].iloc[0]
        if marker == "train":
            return {"metrics": train_metrics, "trades": trades}
        return {"metrics": test_metrics, "trades": trades}

    return backtest_fn


def test_evaluate_candidate_passes_when_every_gate_clears():
    train_metrics = _good_metrics(cagr=15.0, dd=-15.0, trades=50)
    test_metrics = _good_metrics(cagr=10.0, dd=-12.0, trades=40)
    backtest_fn = _make_backtest_fn(train_metrics, test_metrics)
    baseline = _good_metrics(cagr=1.0, dd=-5.0)

    report = evaluate_candidate(
        backtest_fn, _bars_with_marker("train"), _bars_with_marker("test"), {"p": 1}, baseline,
        n_walk_forward_folds=2, n_monte_carlo=50,
    )
    assert isinstance(report, CandidateReport)
    assert report.passed is True
    assert report.reasons == []


def test_evaluate_candidate_fails_on_too_few_train_trades():
    train_metrics = _good_metrics(trades=5)  # below MIN_TRADES
    test_metrics = _good_metrics()
    backtest_fn = _make_backtest_fn(train_metrics, test_metrics)
    baseline = _good_metrics(cagr=1.0)

    report = evaluate_candidate(backtest_fn, _bars_with_marker("train"), _bars_with_marker("test"), {}, baseline, n_monte_carlo=20)
    assert report.passed is False
    assert any("trade count" in r for r in report.reasons)


def test_evaluate_candidate_fails_when_underperforming_baseline():
    train_metrics = _good_metrics(cagr=15.0)
    test_metrics = _good_metrics(cagr=2.0)
    backtest_fn = _make_backtest_fn(train_metrics, test_metrics)
    baseline = _good_metrics(cagr=10.0)  # candidate's TEST cagr (2.0) < baseline (10.0)

    report = evaluate_candidate(backtest_fn, _bars_with_marker("train"), _bars_with_marker("test"), {}, baseline, n_monte_carlo=20)
    assert report.passed is False
    assert any("underperforms baseline" in r for r in report.reasons)


def test_evaluate_candidate_fails_on_excessive_drawdown():
    train_metrics = _good_metrics(dd=-60.0)  # breaches MAX_DRAWDOWN_CAP
    test_metrics = _good_metrics()
    backtest_fn = _make_backtest_fn(train_metrics, test_metrics)
    baseline = _good_metrics(cagr=1.0)

    report = evaluate_candidate(backtest_fn, _bars_with_marker("train"), _bars_with_marker("test"), {}, baseline, n_monte_carlo=20)
    assert report.passed is False
    assert any("drawdown" in r for r in report.reasons)


def test_evaluate_candidate_fails_on_monte_carlo_ruin_probability():
    train_metrics = _good_metrics()
    test_metrics = _good_metrics()
    catastrophic_trades = [{"pnl": -9000.0}, {"pnl": 100.0}]
    backtest_fn = _make_backtest_fn(train_metrics, test_metrics, trades=catastrophic_trades)
    baseline = _good_metrics(cagr=1.0)

    report = evaluate_candidate(
        backtest_fn, _bars_with_marker("train"), _bars_with_marker("test"), {}, baseline,
        n_monte_carlo=100, starting_equity=10_000.0,
    )
    assert report.passed is False
    assert any("ruin probability" in r for r in report.reasons)


def test_register_if_passed_registers_only_on_pass(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    passing = CandidateReport(
        params={"a": 1}, train_metrics=_good_metrics(), test_metrics=_good_metrics(),
        walk_forward={"consistency_pct": 100.0, "worst_drawdown_pct": -5.0},
        monte_carlo={"ruin_probability_pct": 0.0},
        passed=True,
    )
    registered = register_if_passed("my_strategy", "v1", passing, regimes=["trending"])
    assert registered is True
    entry = reg.get("my_strategy", "v1")
    assert entry.state == "VALIDATED"
    assert entry.suited_regimes == ["trending"]


def test_register_if_passed_does_nothing_on_failure(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    failing = CandidateReport(
        params={"a": 1}, train_metrics=_good_metrics(), test_metrics=_good_metrics(),
        walk_forward={"consistency_pct": 0.0, "worst_drawdown_pct": -90.0},
        monte_carlo={"ruin_probability_pct": 50.0},
        passed=False, reasons=["bad"],
    )
    registered = register_if_passed("my_strategy", "v1", failing, regimes=["trending"])
    assert registered is False
    assert reg.get("my_strategy", "v1") is None

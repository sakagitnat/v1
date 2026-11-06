import pandas as pd

from trading.cfd.validation import run_monte_carlo, run_walk_forward, walk_forward_windows


def _bars(n, start="2024-01-01"):
    idx = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": [1.0] * n, "high": [1.0] * n, "low": [1.0] * n, "close": [1.0] * n}, index=idx)


def test_walk_forward_windows_splits_into_n_equal_nonoverlapping_folds():
    bars = {"XAU": _bars(100)}
    folds = walk_forward_windows(bars, n_folds=4)
    assert len(folds) == 4
    total = sum(len(f["XAU"]) for f in folds)
    assert total == 100
    # non-overlapping and sequential
    seen_indices = []
    for f in folds:
        seen_indices.extend(f["XAU"].index.tolist())
    assert seen_indices == sorted(seen_indices)
    assert len(seen_indices) == len(set(seen_indices))


def test_walk_forward_windows_requires_at_least_two_folds():
    import pytest

    with pytest.raises(ValueError):
        walk_forward_windows({"XAU": _bars(10)}, n_folds=1)


def test_run_walk_forward_aggregates_profitable_fold_count():
    bars = {"XAU": _bars(40)}

    # Fake backtest_fn: alternates profitable/unprofitable per call.
    calls = {"n": 0}

    def fake_backtest(fold_bars):
        calls["n"] += 1
        profitable = calls["n"] % 2 == 1
        return {"cagr_pct": 5.0 if profitable else -5.0, "max_drawdown_pct": -10.0 if profitable else -30.0}

    result = run_walk_forward(fake_backtest, bars, n_folds=4)
    assert result["n_folds"] == 4
    assert result["profitable_folds"] == 2
    assert result["consistency_pct"] == 50.0
    assert result["worst_drawdown_pct"] == -30.0
    assert len(result["fold_metrics"]) == 4


def test_run_monte_carlo_with_too_few_trades_returns_empty_result():
    result = run_monte_carlo([{"pnl": 5.0}], starting_equity=100.0)
    assert result["n_simulations"] == 0
    assert result["ruin_probability_pct"] is None


def test_run_monte_carlo_all_winning_trades_has_zero_ruin_probability():
    trades = [{"pnl": 5.0} for _ in range(20)]
    result = run_monte_carlo(trades, starting_equity=100.0, n_simulations=200, seed=42)
    assert result["ruin_probability_pct"] == 0.0
    assert result["final_equity_p50"] == 100.0 + 5.0 * 20


def test_run_monte_carlo_catastrophic_losses_show_high_ruin_probability():
    # A few trades that alone wipe out more than half of equity -- every
    # shuffled ordering should breach the 50% ruin floor eventually.
    trades = [{"pnl": -60.0}, {"pnl": -60.0}, {"pnl": 5.0}, {"pnl": 5.0}]
    result = run_monte_carlo(trades, starting_equity=100.0, n_simulations=200, seed=42, ruin_fraction=0.5)
    assert result["ruin_probability_pct"] == 100.0


def test_run_monte_carlo_is_deterministic_with_a_seed():
    trades = [{"pnl": p} for p in [10, -5, 3, -8, 12, -2, 7, -6, 4, -3]]
    a = run_monte_carlo(trades, starting_equity=100.0, n_simulations=100, seed=7)
    b = run_monte_carlo(trades, starting_equity=100.0, n_simulations=100, seed=7)
    assert a == b


def test_run_monte_carlo_ignores_unattributed_trades():
    trades = [{"pnl": 5.0}, {"pnl": None}, {"pnl": 3.0}]
    result = run_monte_carlo(trades, starting_equity=100.0, n_simulations=50, seed=1)
    assert result["n_trades"] == 2

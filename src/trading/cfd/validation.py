"""Validation -- src/trading/cfd/validation.py

Two checks docs/VISION.md's strategy pipeline calls for beyond the
TRAIN/TEST split scripts/optimize_cfd_strategy.py and scripts/
optimize_cfd_breakout.py already do: Walk-Forward and Monte Carlo /
Stress Test. Both operate on results trading.cfd.backtest.CfdBacktestEngine
already produces -- no new market data or API calls needed.

Walk-Forward: does the already-chosen, FIXED params' edge hold up across
several separate, non-overlapping time windows, not just the one TRAIN/
TEST split -- a strategy that only worked in one lucky stretch of the
TEST period shouldn't pass here even if the TEST split alone looked fine.
This deliberately does NOT re-optimize parameters per fold (grid-
searching per fold would multiply the existing optimizer's runtime by
n_folds, a much heavier undertaking); it checks whether params already
selected are consistently viable across time, which is what "does this
keep working" needs -- not "what's the best possible re-tuning per
period."

Monte Carlo / Stress Test: bootstraps many alternate orderings of the
SAME trades a backtest actually produced, to see whether the backtest's
result depended on a lucky trade sequence -- a real edge should survive
its own trades happening in a different order. This resamples the
strategy's own realized trade outcomes; it is not a market model and
says nothing about trades that never happened.
"""
import random
from typing import Callable, Optional

import pandas as pd


def walk_forward_windows(bars: dict[str, pd.DataFrame], n_folds: int) -> list[dict[str, pd.DataFrame]]:
    """Splits each instrument's bars into n_folds equal, sequential,
    non-overlapping windows (by row count, not calendar time -- history
    depth differs per instrument) -- fold i is a valid, self-contained
    slice of the same price_data shape CfdBacktestEngine.run() already
    accepts."""
    if n_folds < 2:
        raise ValueError("n_folds must be at least 2")
    folds = []
    for i in range(n_folds):
        fold = {}
        for sym, df in bars.items():
            n = len(df)
            start = n * i // n_folds
            end = n * (i + 1) // n_folds
            fold[sym] = df.iloc[start:end]
        folds.append(fold)
    return folds


def run_walk_forward(backtest_fn: Callable[[dict], dict], bars: dict[str, pd.DataFrame], n_folds: int = 4) -> dict:
    """backtest_fn(fold_bars) -> a metrics dict (same shape as
    CfdBacktestEngine.run()["metrics"]), called once per fold with FIXED
    parameters already baked in (e.g. via functools.partial or a
    closure) -- this function never touches parameters itself.

    Returns each fold's metrics plus an aggregate verdict: how many folds
    were profitable (cagr_pct > 0), and the worst single-fold max
    drawdown across all folds -- the number that actually matters for
    "could this have ruined the account in any of the periods tested,"
    not just on average."""
    folds = walk_forward_windows(bars, n_folds)
    fold_metrics = [backtest_fn(fold) for fold in folds]
    profitable_folds = sum(1 for m in fold_metrics if m["cagr_pct"] > 0)
    worst_drawdown_pct = min((m["max_drawdown_pct"] for m in fold_metrics), default=0.0)
    return {
        "n_folds": n_folds,
        "fold_metrics": fold_metrics,
        "profitable_folds": profitable_folds,
        "worst_drawdown_pct": worst_drawdown_pct,
        "consistency_pct": round(profitable_folds / n_folds * 100, 1),
    }


def run_monte_carlo(
    trades: list[dict],
    starting_equity: float,
    n_simulations: int = 1000,
    ruin_fraction: float = 0.5,
    seed: Optional[int] = None,
) -> dict:
    """Bootstraps n_simulations alternate equity paths by reshuffling the
    SAME trade pnl values into random orders (not resampling with
    replacement -- these are the actual trades that happened; the
    question is whether their ORDER mattered, not whether a different set
    of trades might have happened instead). Reports the distribution of
    final equity and max drawdown across simulations, and the fraction of
    simulated paths that ever dropped to or below starting_equity *
    ruin_fraction -- a probability-of-ruin estimate from the strategy's
    own realized trade outcomes.

    Returns an all-None/zero result if there are fewer than 2 priced
    trades to shuffle -- not enough to say anything about ordering."""
    pnls = [t["pnl"] for t in trades if t.get("pnl") is not None]
    if len(pnls) < 2:
        return {
            "n_simulations": 0,
            "n_trades": len(pnls),
            "ruin_probability_pct": None,
            "final_equity_p5": None,
            "final_equity_p50": None,
            "final_equity_p95": None,
            "max_drawdown_p5": None,
            "max_drawdown_p50": None,
        }

    rng = random.Random(seed)
    ruin_floor = starting_equity * ruin_fraction
    final_equities = []
    max_drawdowns = []
    ruin_count = 0

    for _ in range(n_simulations):
        shuffled = pnls[:]
        rng.shuffle(shuffled)
        equity = starting_equity
        peak = starting_equity
        worst_dd = 0.0
        hit_ruin = False
        for pnl in shuffled:
            equity += pnl
            peak = max(peak, equity)
            if peak > 0:
                worst_dd = min(worst_dd, equity / peak - 1)
            if equity <= ruin_floor:
                hit_ruin = True
        final_equities.append(equity)
        max_drawdowns.append(worst_dd * 100)
        if hit_ruin:
            ruin_count += 1

    final_equities.sort()
    max_drawdowns.sort()

    def _pct(sorted_vals: list[float], p: float) -> float:
        idx = min(int(len(sorted_vals) * p), len(sorted_vals) - 1)
        return round(sorted_vals[idx], 2)

    return {
        "n_simulations": n_simulations,
        "n_trades": len(pnls),
        "ruin_probability_pct": round(ruin_count / n_simulations * 100, 2),
        "final_equity_p5": _pct(final_equities, 0.05),
        "final_equity_p50": _pct(final_equities, 0.50),
        "final_equity_p95": _pct(final_equities, 0.95),
        "max_drawdown_p5": _pct(max_drawdowns, 0.05),  # tail case: most-negative 5th percentile
        "max_drawdown_p50": _pct(max_drawdowns, 0.50),
    }

"""Walk-forward validation: the methodology-level fix for a problem a
single TRAIN/TEST split can't catch. Every optimize_cfd_*.py script's
existing discipline (grid-search on TRAIN, confirm once on an untouched
TEST slice) still only ever answers "did this one TRAIN/TEST split
happen to agree?" -- a strategy can pass that gate on luck (the single
TEST window happened to suit it) just as easily as a strategy can fail
it on bad luck (a genuinely robust edge meeting one unfriendly TEST
window). Walk-forward validation replaces the one split with several:
re-run the SAME grid search on each fold's own TRAIN window, evaluate
the winner on that fold's own immediately-following TEST window, and
look at the whole sequence of results -- consistency across folds (not
a single lucky number) is the actual evidence of a real edge.

This module is deliberately strategy-agnostic (no EmaCrossoverStrategy/
CfdBacktestEngine import here): callers supply an `evaluate_fn(kwargs,
bars) -> metrics` (almost always optimize_cfd_strategy.run_backtest
bound to their strategy_cls) and a `select_fn(train_bars) -> (kwargs,
train_metrics)` (their own grid search + TRAIN-side selection, e.g.
optimize_cfd_strategy.py's existing pool/calmar logic) and this module
owns only the walk-forward splitting, fold loop, and aggregate
reporting -- the same "shared orchestration, strategy-specific grid"
split optimize_cfd_breakout.py etc. already use for the single-split
TRAIN/TEST helpers.

Scheme: ANCHORED (expanding-window) walk-forward, the simpler and more
data-efficient of the two common variants (the other being a fixed-size
rolling window) -- chosen because this project's history windows are
already short (Deriv's own M15 candles cap at ~3 months; see
optimize_cfd_strategy.py's docstring), and an expanding TRAIN window
wastes none of it the way a fixed rolling window would by discarding
early data as it slides forward. n_folds folds need n_folds+1 equal-ish
segments of the data: segment 0 is the minimum burn-in TRAIN every fold
shares, and each of segments 1..n_folds is one fold's TEST window (with
that fold's TRAIN being everything strictly before it)."""
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class WalkForwardFold:
    index: int
    train_bars: dict[str, pd.DataFrame]
    test_bars: dict[str, pd.DataFrame]
    train_span: tuple
    test_span: tuple


@dataclass
class FoldResult:
    fold: int
    kwargs: dict
    train_metrics: dict
    test_metrics: dict
    beat_baseline: bool


@dataclass
class WalkForwardReport:
    folds: list = field(default_factory=list)
    """list[FoldResult], oldest fold first."""

    @property
    def n_folds(self) -> int:
        return len(self.folds)

    def test_metric_values(self, key: str) -> list[float]:
        return [f.test_metrics[key] for f in self.folds]

    def mean_test(self, key: str) -> float:
        values = self.test_metric_values(key)
        return sum(values) / len(values) if values else 0.0

    def worst_test(self, key: str) -> float:
        values = self.test_metric_values(key)
        return min(values) if values else 0.0

    def fraction_beating_baseline(self) -> float:
        if not self.folds:
            return 0.0
        return sum(1 for f in self.folds if f.beat_baseline) / len(self.folds)

    def param_stability(self) -> dict[str, set]:
        """Every distinct value each selected parameter took across
        folds -- a strategy whose "winning" parameters are a different
        corner of the grid every fold is telling you the single-split
        version's one winning combo was this fold's lucky draw, not a
        stable edge, even if every individual fold's TEST looked fine
        in isolation."""
        if not self.folds:
            return {}
        keys = self.folds[0].kwargs.keys()
        return {k: {f.kwargs[k] for f in self.folds} for k in keys}


def make_walk_forward_folds(bars: dict[str, pd.DataFrame], n_folds: int) -> list[WalkForwardFold]:
    """Splits each instrument's bars into n_folds anchored walk-forward
    folds (see module docstring). Every instrument is split at the same
    fractional positions (mirroring optimize_cfd_strategy.split()'s own
    proportional-not-calendar-date approach, since fetched history
    length isn't known ahead of a live fetch and can differ slightly
    per instrument)."""
    if n_folds < 1:
        raise ValueError(f"n_folds must be >= 1, got {n_folds}")

    n_segments = n_folds + 1
    folds: list[WalkForwardFold] = []

    for fold_i in range(1, n_segments):
        train_bars: dict[str, pd.DataFrame] = {}
        test_bars: dict[str, pd.DataFrame] = {}
        train_spans = []
        test_spans = []

        for sym, df in bars.items():
            n = len(df)
            train_end = int(n * fold_i / n_segments)
            test_end = int(n * (fold_i + 1) / n_segments)
            train_df = df.iloc[:train_end]
            test_df = df.iloc[train_end:test_end]
            train_bars[sym] = train_df
            test_bars[sym] = test_df
            if not train_df.empty:
                train_spans.append((train_df.index[0], train_df.index[-1]))
            if not test_df.empty:
                test_spans.append((test_df.index[0], test_df.index[-1]))

        train_span = (min(s[0] for s in train_spans), max(s[1] for s in train_spans)) if train_spans else (None, None)
        test_span = (min(s[0] for s in test_spans), max(s[1] for s in test_spans)) if test_spans else (None, None)
        folds.append(WalkForwardFold(fold_i, train_bars, test_bars, train_span, test_span))

    return folds


def run_walk_forward(bars: dict[str, pd.DataFrame], n_folds: int, select_fn, evaluate_fn, baseline_kwargs: dict = None) -> WalkForwardReport:
    """select_fn(train_bars) -> (kwargs, train_metrics) picks one
    candidate per fold the same way the single-split script's grid
    search + TRAIN-side ranking already does (callers own that logic
    entirely -- this function never looks inside kwargs). evaluate_fn
    (kwargs, bars) -> metrics backtests any kwargs on any bars --
    almost always optimize_cfd_strategy.run_backtest bound to the
    caller's strategy_cls. baseline_kwargs (default {}, the strategy's
    unmodified defaults) is evaluated on every fold's TEST too, so
    beat_baseline means the same thing every fold."""
    baseline_kwargs = {} if baseline_kwargs is None else baseline_kwargs
    report = WalkForwardReport()

    for fold in make_walk_forward_folds(bars, n_folds):
        kwargs, train_metrics = select_fn(fold.train_bars)
        test_metrics = evaluate_fn(kwargs, fold.test_bars)
        baseline_test_metrics = evaluate_fn(baseline_kwargs, fold.test_bars)
        beat_baseline = test_metrics["cagr_pct"] > baseline_test_metrics["cagr_pct"]
        report.folds.append(FoldResult(fold.index, kwargs, train_metrics, test_metrics, beat_baseline))

    return report

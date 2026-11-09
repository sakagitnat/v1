"""Research Lab -- src/trading/cfd/research_lab.py

Generates and evaluates strategy parameter candidates, then auto-
registers the ones that clear every automated validation stage docs/
VISION.md's pipeline calls for (Backtest -> Out-of-Sample -> Walk-Forward
-> Monte Carlo) into the Strategy Registry as VALIDATED -- never higher.
VALIDATED is exactly as far as an automated pipeline is allowed to take
a candidate: the remaining steps (Paper Trading -> Promote) still need a
human to advance it further (`cfd_cli.py promote-strategy ... PAPER` /
`... ACTIVE`), per docs/VISION.md's rule against promoting a strategy on
backtest results alone and against hot-editing a live strategy without
validation.

This does NOT invent new strategy logic (no code generation) -- "new
candidate" here means a new, systematically-searched parameter set for
an EXISTING strategy class (trading.cfd.strategy_registry.
STRATEGY_CLASSES), the same shape scripts/optimize_cfd_strategy.py and
scripts/optimize_cfd_breakout.py already search by hand. What's new is
that a candidate clearing every gate gets registered automatically,
audit trail and all, instead of a human reading a printed table and
deciding whether to type the registration command themselves.
"""
import itertools
from dataclasses import dataclass, field
from typing import Callable, Optional

from trading.cfd.strategy_registry import LifecycleState, register
from trading.cfd.validation import run_monte_carlo, run_walk_forward

MIN_TRADES = 20
MAX_DRAWDOWN_CAP = -25.0
MIN_WALK_FORWARD_CONSISTENCY_PCT = 50.0  # at least half the walk-forward folds must be profitable
MAX_RUIN_PROBABILITY_PCT = 5.0  # Monte Carlo: at most this % of simulated paths may hit the ruin floor


def generate_candidate_params(param_grid: dict, filter_fn: Optional[Callable[[dict], bool]] = None) -> list[dict]:
    """Expands a grid of parameter variations into every valid
    combination -- the same itertools.product shape scripts/
    optimize_cfd_strategy.py and scripts/optimize_cfd_breakout.py already
    use by hand, factored out here so they and the Research Lab share one
    implementation instead of three copies. filter_fn, if given, drops
    combinations that don't make structural sense (e.g. fast_span >=
    slow_span) -- the same role as those scripts' inline filters."""
    keys = list(param_grid.keys())
    combos = [dict(zip(keys, values)) for values in itertools.product(*param_grid.values())]
    if filter_fn:
        combos = [c for c in combos if filter_fn(c)]
    return combos


@dataclass
class CandidateReport:
    params: dict
    train_metrics: dict
    test_metrics: dict
    walk_forward: dict
    monte_carlo: dict
    passed: bool
    reasons: list = field(default_factory=list)


def evaluate_candidate(
    backtest_fn: Callable[[dict, dict], dict],
    train_bars: dict,
    test_bars: dict,
    params: dict,
    baseline_test_metrics: dict,
    n_walk_forward_folds: int = 4,
    n_monte_carlo: int = 1000,
    starting_equity: float = 10_000.0,
) -> CandidateReport:
    """backtest_fn(params, bars) -> a full engine.run() result dict (with
    "trades" and "metrics" keys -- CfdBacktestEngine.run()'s own return
    shape). Runs every gate in order: TRAIN min-trades + positive CAGR +
    drawdown cap -> TEST beats baseline and clears the drawdown cap ->
    walk-forward across TEST -> Monte Carlo on TEST's own trades.
    Evaluates every gate (doesn't stop at the first failure) so a
    rejected candidate's report explains everything wrong with it, not
    just the first problem found."""
    reasons = []

    train_result = backtest_fn(params, train_bars)
    train_metrics = train_result["metrics"]
    if train_metrics["num_trades"] < MIN_TRADES:
        reasons.append(f"TRAIN trade count {train_metrics['num_trades']} < minimum {MIN_TRADES}")
    if train_metrics["cagr_pct"] <= 0:
        reasons.append(f"TRAIN CAGR {train_metrics['cagr_pct']}% is not positive")
    if train_metrics["max_drawdown_pct"] < MAX_DRAWDOWN_CAP:
        reasons.append(f"TRAIN max drawdown {train_metrics['max_drawdown_pct']}% breaches cap {MAX_DRAWDOWN_CAP}%")

    test_result = backtest_fn(params, test_bars)
    test_metrics = test_result["metrics"]
    if test_metrics["cagr_pct"] <= 0:
        reasons.append(f"TEST CAGR {test_metrics['cagr_pct']}% is not positive")
    if test_metrics["max_drawdown_pct"] < MAX_DRAWDOWN_CAP:
        reasons.append(f"TEST max drawdown {test_metrics['max_drawdown_pct']}% breaches cap {MAX_DRAWDOWN_CAP}%")
    if test_metrics["cagr_pct"] < baseline_test_metrics["cagr_pct"]:
        reasons.append(f"TEST CAGR {test_metrics['cagr_pct']}% underperforms baseline {baseline_test_metrics['cagr_pct']}%")

    walk_forward = run_walk_forward(
        lambda fold: backtest_fn(params, fold)["metrics"], test_bars, n_folds=n_walk_forward_folds
    )
    if walk_forward["consistency_pct"] < MIN_WALK_FORWARD_CONSISTENCY_PCT:
        reasons.append(
            f"walk-forward consistency {walk_forward['consistency_pct']}% < minimum {MIN_WALK_FORWARD_CONSISTENCY_PCT}%"
        )
    if walk_forward["worst_drawdown_pct"] < MAX_DRAWDOWN_CAP:
        reasons.append(f"worst walk-forward fold drawdown {walk_forward['worst_drawdown_pct']}% breaches cap {MAX_DRAWDOWN_CAP}%")

    monte_carlo = run_monte_carlo(test_result["trades"], starting_equity, n_simulations=n_monte_carlo)
    if monte_carlo["ruin_probability_pct"] is not None and monte_carlo["ruin_probability_pct"] > MAX_RUIN_PROBABILITY_PCT:
        reasons.append(f"Monte Carlo ruin probability {monte_carlo['ruin_probability_pct']}% > maximum {MAX_RUIN_PROBABILITY_PCT}%")

    return CandidateReport(
        params=params,
        train_metrics=train_metrics,
        test_metrics=test_metrics,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        passed=not reasons,
        reasons=reasons,
    )


def register_if_passed(strategy_name: str, version: str, report: CandidateReport, regimes: list) -> bool:
    """Registers a passing candidate as VALIDATED -- never higher (see
    module docstring). Does nothing and returns False for a candidate
    that didn't pass: rejected candidates are never registered at all,
    not registered-then-retired, so the registry only ever holds
    strategies that genuinely cleared automated validation and are
    waiting on a human's paper-trading decision."""
    if not report.passed:
        return False
    register(
        strategy_name,
        version,
        report.params,
        initial_state=LifecycleState.VALIDATED,
        note=(
            f"Auto-validated by Research Lab: TRAIN cagr={report.train_metrics['cagr_pct']}% "
            f"maxdd={report.train_metrics['max_drawdown_pct']}%, TEST cagr={report.test_metrics['cagr_pct']}% "
            f"maxdd={report.test_metrics['max_drawdown_pct']}%, walk-forward consistency="
            f"{report.walk_forward['consistency_pct']}%, Monte Carlo ruin probability="
            f"{report.monte_carlo['ruin_probability_pct']}%."
        ),
        regimes=regimes,
    )
    return True

"""Portfolio / Allocation Decision -- src/trading/cfd/portfolio_allocator.py

Closes revised-gap-analysis item #1 in docs/ARCHITECTURE_AUDIT.md: the
Strategy Registry and Selector used to enforce "at most one ACTIVE
strategy per regime" and pick that single winner, when docs/VISION.md's
revised pipeline wants a real Portfolio/Allocation Decision stage --
several strategies suited to the same regime can be ACTIVE at once, each
getting a share of the risk budget weighted by recent performance, not a
single hardcoded winner.

compute_allocations() turns the current ACTIVE roster and trade history
into a weight per strategy (summing to 1.0 across all ACTIVE strategies,
regardless of regime -- trading.cfd.selector.select_for_entry only looks
at the weights of whichever subset actually matches a given regime).
risk_scale_factor() then converts one strategy's weight into a per-trade
risk multiplier relative to the equal-weight baseline.

This module only ever *redistributes* risk among already-ACTIVE
strategies -- it never invents new risk, never exceeds what a human
already configured (risk_scale_factor is capped at 1.0), and never
decides a strategy shouldn't trade at all (that's trading.cfd.
decay_supervisor's job, via detect_degradation -- a strategy this module
would weight near the floor is exactly the kind of thing decay_supervisor
is watching to demote outright). Per docs/VISION.md's "Autonomy
boundaries": shifting how much of the existing budget each strategy gets
only ever lowers or holds risk for any one strategy, never raises it
past what's already configured -- so it needs no human approval, same as
demotion.
"""
from trading.cfd.performance import compute_performance
from trading.cfd.strategy_registry import StrategyEntry
from trading.config import settings

MIN_TRADES_FOR_WEIGHTING = 10
"""Below this many of its own closed trades, a strategy's expectancy is
too noisy to weight by -- treated as a breakeven strategy (the same floor
score every strategy starts at) instead, so a freshly-promoted strategy
is neither penalized nor favored by a sample too small to mean anything."""

WEIGHT_FLOOR = 0.05
"""Every ACTIVE strategy's raw score starts here, before performance is
layered on top -- guarantees no ACTIVE strategy is starved to a near-zero
share purely by this stage. Zeroing a strategy out entirely is
decay_supervisor's decision (an explicit demotion, audited and logged),
never an incidental side effect of allocation math."""


def _tag(entry: StrategyEntry) -> str:
    return f"{entry.name}@{entry.version}"


def compute_allocations(trades: list[dict], active_entries: list[StrategyEntry]) -> dict[str, float]:
    """Returns {"name@version": weight} for every entry in active_entries,
    weights summing to 1.0. A strategy with >= MIN_TRADES_FOR_WEIGHTING of
    its own trades gets a raw score of WEIGHT_FLOOR + max(0, expectancy);
    one with less history gets exactly WEIGHT_FLOOR (same as a breakeven
    strategy) until it earns more. Negative expectancy never pulls a score
    below the floor -- a strategy losing badly enough to matter should be
    demoted outright (decay_supervisor), not slowly starved here."""
    if not active_entries:
        return {}
    if len(active_entries) == 1:
        return {_tag(active_entries[0]): 1.0}

    scores = {}
    for entry in active_entries:
        tag = _tag(entry)
        own = [t for t in trades if t.get("strategy") == tag and t.get("pnl") is not None]
        if len(own) < MIN_TRADES_FOR_WEIGHTING:
            scores[tag] = WEIGHT_FLOOR
        else:
            perf = compute_performance(own, starting_equity=settings.cfd_virtual_starting_capital)
            scores[tag] = WEIGHT_FLOOR + max(0.0, perf["expectancy"])

    total = sum(scores.values())
    return {tag: score / total for tag, score in scores.items()}


def risk_scale_factor(weight: float, n_active: int) -> float:
    """Converts a normalized allocation weight (from compute_allocations,
    summed to 1.0 across ALL active strategies) into a per-trade risk
    multiplier relative to the equal-weight baseline -- an equal share
    (1 / n_active) scales to 1.0, i.e. no change from today's fixed
    risk_per_trade. Capped at 1.0: the strategy currently getting the
    largest share of the budget can reach the full configured
    risk_per_trade, never more, so allocation can only ever redistribute
    risk *down* for lower-conviction strategies, never up past what a
    human already set -- see this module's docstring."""
    if n_active <= 0:
        return 1.0
    return min(1.0, weight * n_active)

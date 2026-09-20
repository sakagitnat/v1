"""Strategy Selector (CFD) -- src/trading/cfd/selector.py

Picks which registered ACTIVE strategy, if any, should open a NEW
position on a given instrument this run -- matching the instrument's
current regime (trading.cfd.regime) against each ACTIVE strategy's
suited_regimes (trading.cfd.strategy_registry.StrategyEntry). Returns
None -- an explicit NO TRADE decision, never a fallback guess -- when the
regime can't be classified yet (trading.cfd.regime.UNKNOWN) or no ACTIVE
strategy is suited to it.

Only decides NEW entries into a flat instrument. An already-open position
is always managed to its exit by the exact strategy version that opened
it (see scheduler.py), regardless of what regime says now or which
strategy is ACTIVE by the time it closes -- so promoting a new strategy,
or pausing/retiring one, can never retroactively change how an existing
position gets closed out.

Per docs/VISION.md's revised "Portfolio / Allocation Decision" stage,
more than one ACTIVE strategy may be suited to the same regime at once
(trading.cfd.strategy_registry no longer enforces "at most one ACTIVE
per regime" -- see its docstring), and per Revision 3 gap #3
(docs/ARCHITECTURE_AUDIT.md), an instrument is no longer limited to one
open position at a time: `exclude_tags` (scheduler.py passes every
strategy tag that already has a leg open on THIS instrument) removes
those from consideration first, so a genuinely different strategy can
still open its own independent position on an instrument another
strategy already holds one on -- two different structural bets on the
same instrument are two theses, not one, and
trading.cfd.portfolio_risk's thesis/correlated/portfolio ceilings (keyed
on instrument+side, never on strategy) already aggregate their risk
correctly regardless of which strategy opened them, so nothing else
needs to change to make this safe. Among whatever regime-suited
strategies remain after that exclusion, this picks the one
trading.cfd.portfolio_allocator currently weights highest (recent
performance -- ties broken deterministically by name/version, never by
insertion order or randomness) for THIS instrument's next new position
this run -- still only one NEW entry decision per instrument per run
(scheduler.py's set_pending_entry/clear_pending-entry idempotency
tracking stays one record per instrument per run), not a burst of
several at once.
"""
from typing import Optional

from trading.cfd.regime import UNKNOWN
from trading.cfd.strategy_registry import LifecycleState, StrategyEntry, list_by_state


def _tag(entry: StrategyEntry) -> str:
    return f"{entry.name}@{entry.version}"


def select_for_entry(
    regime: str,
    allocations: Optional[dict[str, float]] = None,
    exclude_tags: Optional[set[str]] = None,
) -> Optional[StrategyEntry]:
    """allocations: trading.cfd.portfolio_allocator.compute_allocations()'s
    output ({"name@version": weight}, summed to 1.0 across every ACTIVE
    strategy) -- used only to break a tie among multiple regime-suited
    matches. Missing entirely, or missing a specific match's tag, is
    treated as weight 0.0 for that match (never crashes, never favors an
    unweighted strategy over a weighted one).

    exclude_tags: strategy tags ("name@version") to skip even if
    otherwise regime-suited -- scheduler.py passes the strategies that
    already have a position open on this instrument, so this never
    doubles up the SAME strategy's thesis on one instrument (that would
    be exactly the disguised-risk-split docs/VISION.md forbids), while
    still allowing a genuinely different ACTIVE strategy to open its own
    independent position there."""
    if regime == UNKNOWN:
        return None
    active = list_by_state(LifecycleState.ACTIVE)
    exclude_tags = exclude_tags or set()
    matches = [e for e in active if regime in (e.suited_regimes or []) and _tag(e) not in exclude_tags]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    allocations = allocations or {}
    return max(matches, key=lambda e: (allocations.get(_tag(e), 0.0), e.name, e.version))

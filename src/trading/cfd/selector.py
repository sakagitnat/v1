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

trading.cfd.strategy_registry.set_state()/register() enforce "at most one
ACTIVE strategy per regime" at promotion time, so a match here should
never be ambiguous -- the RuntimeError below is a last-resort integrity
check, not the normal way this gets decided.

Today only one strategy is ever ACTIVE at all (ema_crossover, suited to
"trending"), so in practice this mostly acts as a NO TRADE gate during a
"ranging" regime -- no mean-reversion/range strategy is registered yet to
fill that gap (see docs/ARCHITECTURE_AUDIT.md).
"""
from typing import Optional

from trading.cfd.regime import UNKNOWN
from trading.cfd.strategy_registry import LifecycleState, StrategyEntry, list_by_state


def select_for_entry(regime: str) -> Optional[StrategyEntry]:
    if regime == UNKNOWN:
        return None
    active = list_by_state(LifecycleState.ACTIVE)
    matches = [e for e in active if regime in (e.suited_regimes or [])]
    if not matches:
        return None
    if len(matches) > 1:
        names = ", ".join(f"{e.name}@{e.version}" for e in matches)
        raise RuntimeError(
            f"{len(matches)} ACTIVE strategies are suited to regime {regime!r} ({names}) -- this should be "
            "impossible (strategy_registry.set_state() is supposed to prevent regime overlap). Pause all but one."
        )
    return matches[0]

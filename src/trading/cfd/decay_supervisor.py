"""Autonomous Strategy Demotion -- src/trading/cfd/decay_supervisor.py

Implements the "Strategy Decay Detection -> Demote/Pause" stage of
docs/VISION.md's parallel research track, and the specific autonomy its
"Autonomy boundaries" section grants the AI: acting on its own to REDUCE
risk when trading.cfd.failure_analysis.detect_degradation() flags an
ACTIVE strategy as decayed. This module never promotes, never raises
risk, and never touches anything a human would need to approve (a hard
risk ceiling, real money, the safety architecture itself) -- it only
ever moves a strategy from ACTIVE to PAUSED, on evidence, through the
normal audited trading.cfd.strategy_registry.set_state() path, exactly
like a human-issued `cfd_cli.py promote-strategy ... PAUSED` command,
just triggered automatically instead of waiting for one.

Before this module existed, trading.cfd.manager_report already computed
the same degradation signal and printed a recommended command -- but
recommending isn't acting, and docs/VISION.md's 2026-09-20 revision was
explicit that routine demotions shouldn't need a human to click approve
each time. This is what makes that actually true.

Sending a demoted strategy back through the Research Lab for
re-validation (the vision's "Demote/Pause -> Research Lab" arrow) is
still a separate, heavier step (a live data fetch + grid search) --
demotion here only ever removes it from live trading; re-validating it
is scripts/research_cfd_strategy.py's job, run manually or on its own
schedule, not triggered synchronously by a demotion.
"""
from trading.cfd.failure_analysis import detect_degradation
from trading.cfd.strategy_registry import LifecycleState, list_by_state, set_state
from trading.logging_utils import get_logger

logger = get_logger(__name__)


def run_autonomous_demotion(trades: list[dict]) -> list[dict]:
    """Checks every currently-ACTIVE strategy for degradation
    (trading.cfd.failure_analysis.detect_degradation) and demotes
    (ACTIVE -> PAUSED) any that qualify. Only ACTIVE entries are ever
    checked -- a CANDIDATE/VALIDATED/PAUSED strategy's trade history
    (e.g. from paper trading) is never acted on here, since it isn't
    live and demoting it would mean nothing.

    Returns a list of {"strategy": tag, "reason": ...} for every
    demotion actually applied this call, so a caller (scheduler.py) can
    log/notify and immediately exclude these strategies from the same
    run's trading without a second registry read."""
    demotions = []
    for entry in list_by_state(LifecycleState.ACTIVE):
        tag = f"{entry.name}@{entry.version}"
        result = detect_degradation(trades, tag)
        if result is None or not result["degraded"]:
            continue
        reason = f"autonomous demotion: {result['reason']}"
        set_state(entry.name, entry.version, LifecycleState.PAUSED, reason=reason)
        logger.warning("Autonomously demoted %s to PAUSED -- %s", tag, result["reason"])
        demotions.append({"strategy": tag, "reason": reason})
    return demotions

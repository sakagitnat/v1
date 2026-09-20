"""Automatic Drawdown-Tiered Risk Reduction -- src/trading/cfd/drawdown_monitor.py

Closes Revision 3 gap #4 (docs/ARCHITECTURE_AUDIT.md): trading.cfd.
operating_mode's Defensive/Normal/Aggressive/Recovery multipliers
existed, but nothing ever switched modes automatically based on current
drawdown severity -- a human had to notice and run `cfd_cli.py
set-mode`. This is a risk-REDUCING autonomous action (docs/VISION.md's
"Autonomy boundaries" -- the AI may act on its own to lower risk, never
to raise it), so it needs no human approval, the same authority
trading.cfd.decay_supervisor already has for demoting a decaying
strategy.

Drawdown here is measured from a HIGH-WATER-MARK of virtual equity (see
trading.cfd.smoothed_equity.update_high_water_mark), not from the
account's starting balance -- so it reflects "how far below the best
we've ever done," the standard definition, not "how far below where we
started" (which would read 0% even right after giving back a large
unrealized gain).

Tiers (illustrative default thresholds, all configurable via Settings,
none empirically validated -- same status as every other threshold in
this project):

    < moderate_pct  -> multiplier 1.0 (no change)
    >= moderate_pct -> multiplier moderate_multiplier (default 0.75)
    >= deep_pct     -> multiplier deep_multiplier (default 0.5)
    >= severe_pct   -> multiplier 0.0 (new entries halted entirely --
                       every strategy's risk-budgeted stake comes out to
                       $0 and SKIP TRADEs, the same mechanism the
                       existing daily-loss/capital-floor halts use)

The resulting multiplier STACKS with (multiplies further on top of)
whatever trading.cfd.operating_mode's human-set mode already computes --
it can only ever shrink effective risk further, never override a
human's mode choice upward. It never touches an ALREADY-open position
(no forced exit) -- only new entries are affected, the same "reduce
future risk, don't panic-close open ones" philosophy as the daily-loss
circuit breaker and capital floor.

Explicitly does NOT try to distinguish a random losing streak from
genuine strategy decay -- that's trading.cfd.decay_supervisor's job
(per-strategy, via detect_degradation's statistical comparison). This
module is deliberately blunt and portfolio-wide: whatever the cause,
being meaningfully below the high-water-mark means the system trades
smaller until equity recovers, full stop.
"""
from dataclasses import dataclass

NORMAL = "normal"
MODERATE = "moderate"
DEEP = "deep"
SEVERE = "severe"


@dataclass
class DrawdownThresholds:
    moderate_pct: float
    deep_pct: float
    severe_pct: float
    moderate_multiplier: float
    deep_multiplier: float


def classify_drawdown_tier(current_equity: float, high_water_mark: float, thresholds: DrawdownThresholds) -> str:
    """high_water_mark <= 0 (no observations yet) reads as NORMAL --
    there's nothing to be "below" yet."""
    if high_water_mark <= 0:
        return NORMAL
    drawdown_pct = max(0.0, (high_water_mark - current_equity) / high_water_mark)
    if drawdown_pct >= thresholds.severe_pct:
        return SEVERE
    if drawdown_pct >= thresholds.deep_pct:
        return DEEP
    if drawdown_pct >= thresholds.moderate_pct:
        return MODERATE
    return NORMAL


def drawdown_risk_multiplier(tier: str, thresholds: DrawdownThresholds) -> float:
    if tier == SEVERE:
        return 0.0
    if tier == DEEP:
        return thresholds.deep_multiplier
    if tier == MODERATE:
        return thresholds.moderate_multiplier
    return 1.0

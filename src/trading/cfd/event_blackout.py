"""Economic Event Blackout -- src/trading/cfd/event_blackout.py

Closes part of the joint Claude/GPT design discussion in GitHub issue #4
("AI Trading Manager: market/news research + strategy improvement loop")
and issue #5 ("MASTER REQUIREMENTS"): both independently ranked approach
D (news as an event blackout / NO TRADE filter) as the strongest first
step for incorporating market/news context, for three reasons neither
of the other five hypotheses shares -- see issue #4 for the full
comparison:

  1. It needs only a *scheduled* economic calendar (Fed/NFP/CPI release
     times, published weeks in advance), not freeform news text -- a
     structured-data problem, not an NLP one, which sidesteps the
     sharpest failure mode discussed there (timestamp/alignment leakage
     from unreliable "discovery time" news archives).
  2. It only ever *removes* opportunity, never adds a directional bet --
     the same NO TRADE philosophy docs/VISION.md already establishes,
     and the same shape trading.cfd.drawdown_monitor's severe tier
     already uses ($0 risk budget -> SKIP TRADE).
  3. The stock (Alpaca) side of this repo already has a working,
     narrowly-scoped precedent for exactly this shape (README's
     "Ongoing news monitoring": pause new entries for macro/systemic
     risk, never touches sizing or an existing position) -- this is
     that same pattern, not a new architectural layer.

This module is ONLY the pure blackout-window mechanism -- a timestamp
check against a list of scheduled events, with no data source, no
network call, and no wiring into scheduler.py's live entry logic yet.
That's deliberate, not an oversight: docs/VISION.md's own discipline
(every candidate proves itself on a real TRAIN/TEST split before it
touches a live decision -- see optimize_cfd_strategy.py's docstring on
why adx_threshold "doesn't get to skip the overfit check just because
the hypothesis behind it is intuitive") applies to this exactly the way
it applied to mean_reversion@v1 and rsi_reversion@v1, both retired this
session on honest negative TRAIN/TEST results. A blackout filter is no
different: it needs the same backtested evidence (does it actually
improve expectancy/drawdown vs. a price-only baseline, or just cost
opportunity for no benefit) before scheduler.py's real entry logic ever
calls it. What's still needed before that experiment can run: a
concrete, reliably-timestamped economic calendar data source -- research
question posted back to GPT in issue #4 as the natural fit for its
stated "market/news analyst" role in the collaboration model, rather
than guessed at here.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class EconomicEvent:
    """One scheduled high-impact event -- e.g. a Fed rate decision, NFP,
    or CPI release. `scheduled_at` must be UTC and must be the event's
    actual, known-in-advance release time (this is what makes approach D
    backtestable without the timestamp-leakage risk freeform news text
    carries -- see this module's docstring)."""

    name: str
    scheduled_at: datetime
    impact: str = "high"
    """"high"/"medium"/"low" -- only "high" is blocked by default
    (min_impact param below), so a lower-impact release doesn't halt
    trading unless explicitly asked to."""


_IMPACT_RANK = {"low": 0, "medium": 1, "high": 2}


def in_blackout_window(
    now: datetime,
    events: list[EconomicEvent],
    window_before_minutes: int = 15,
    window_after_minutes: int = 15,
    min_impact: str = "high",
) -> Optional[EconomicEvent]:
    """Returns the first event whose blackout window
    [scheduled_at - window_before, scheduled_at + window_after] contains
    `now`, or None if `now` falls in no event's window. Only events whose
    impact rank is >= min_impact's rank are considered -- e.g. the
    default min_impact="high" means a "medium"-impact release never
    triggers a blackout on its own.

    window_before_minutes/window_after_minutes are asymmetric on
    purpose in principle (kept equal only as a starting default): a
    release's pre-event drift and post-event volatility spike don't
    necessarily need the same width, and the right values are exactly
    the kind of hyperparameter that needs its own TRAIN/TEST validation
    (see module docstring) -- never picked by intuition and shipped
    straight to live trading.

    Pure function, no I/O -- `events` is supplied by the caller (a
    backtest's fixture data today; a validated live calendar source
    later, once one is chosen and proven). Deliberately returns the
    matched event, not just True/False, so a caller can log or record
    *why* a window was blacked out, not just that it was."""
    if min_impact not in _IMPACT_RANK:
        raise ValueError(f"min_impact must be one of {list(_IMPACT_RANK)}, got {min_impact!r}")
    min_rank = _IMPACT_RANK[min_impact]
    before = timedelta(minutes=window_before_minutes)
    after = timedelta(minutes=window_after_minutes)
    for event in events:
        if _IMPACT_RANK.get(event.impact, 0) < min_rank:
            continue
        window_start = event.scheduled_at - before
        window_end = event.scheduled_at + after
        if window_start <= now <= window_end:
            return event
    return None

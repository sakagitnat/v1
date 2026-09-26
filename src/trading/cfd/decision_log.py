"""Append-only decision log for every CFD opportunity evaluation.

Separate from the closed-trade database: records TRADE / NO_TRADE / REJECTED /
ERROR decisions so the manager can learn from opportunities it deliberately
skipped, not only from positions that were opened and later closed.

``context`` is structured shadow telemetry.  When a caller does not supply it,
we snapshot the versioned official event calendar at decision time.  This is
measurement only: it cannot block, create, resize, or redirect a trade.  The
point is to accumulate honest event-window/non-event observations before the
blackout hypothesis is allowed through validation.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_PATH = Path(__file__).resolve().parents[3] / "state" / "cfd_decisions.jsonl"


def _shadow_context(now: datetime) -> dict:
    """Point-in-time research context; failure degrades to explicit unknown.

    Calendar telemetry must never be on the execution-critical path.  An
    import/data problem therefore records availability=false rather than
    failing the scheduler or pretending there was no event.
    """
    try:
        from trading.cfd.event_blackout import in_blackout_window
        from trading.cfd.event_calendar import EVENTS, SNAPSHOT_VERSION
        event = in_blackout_window(now, EVENTS)
        return {
            "event_calendar_available": True,
            "event_calendar_version": SNAPSHOT_VERSION,
            "event_blackout_shadow": event is not None,
            "event_name": event.name if event is not None else None,
            "event_impact": event.impact if event is not None else None,
        }
    except Exception as exc:  # telemetry may not stop trading
        return {
            "event_calendar_available": False,
            "event_blackout_shadow": None,
            "event_context_error": type(exc).__name__,
        }


def record_decision(
    instrument: str,
    outcome: str,
    reason: str,
    *,
    regime: Optional[str] = None,
    strategy: Optional[str] = None,
    run_id: Optional[str] = None,
    bridge_command_id: Optional[str] = None,
    context: Optional[dict] = None,
) -> dict:
    now = datetime.now(timezone.utc)
    row = {
        "timestamp": now.isoformat(),
        "instrument": instrument,
        "outcome": outcome,
        "reason": reason,
        "regime": regime,
        "strategy": strategy,
        "run_id": run_id,
        "bridge_command_id": bridge_command_id,
        "context": _shadow_context(now) if context is None else context,
    }
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with _PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return row

def load_decisions() -> list[dict]:
    if not _PATH.exists():
        return []
    rows = []
    for line in _PATH.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

"""Timeframe-champion strategy assignment.

Four isolated $100 virtual accounts (trading.cfd.virtual_accounts:
core_h1, champion_m30, champion_h4, champion_d1), one per timeframe the
user asked for -- each trades whichever strategy has most recently
cleared TRAIN/TEST/walk-forward validation at that timeframe's own
granularity, or nothing at all if none has yet (NO TRADE is a valid,
expected state here, same as everywhere else in this project).

Deliberately NOT stored in trading.cfd.strategy_registry: that registry
is the single H1 production pool's lifecycle (RESEARCH->...->ACTIVE) and
is read by the live scheduler.run_once() -- reusing it for four
independent per-timeframe assignments would force a single-timeline
model onto something that is explicitly meant to vary independently per
timeframe. This is a separate, lighter-weight assignment record: which
concrete (strategy, params) pair a champion account is currently
running, and what validation justified picking it. It reuses
strategy_registry.STRATEGY_CLASSES to build the actual strategy object,
since that mapping is just "name -> class", not part of the lifecycle
machinery itself.

Also deliberately NOT stored via VirtualAccountSpec.strategy_tag: that
field is reconciled back to the static DEFAULT_VIRTUAL_ACCOUNTS value on
every ensure_virtual_accounts() call (see that module), which would
silently overwrite a champion's live assignment back to None on the very
next run.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from trading.cfd.state import get_timeframe_champions, set_timeframe_champions
from trading.cfd.strategy_registry import STRATEGY_CLASSES

# account_id -> (granularity_seconds, context_timeframes). H1/core_h1 is
# already wired directly into scheduler.run_once() and isn't evaluated by
# champion_scheduler.py -- listed here too only so callers have one place
# to look up every champion's granularity/context, not because this
# module manages its assignment (core_h1 stays registry-driven, per
# scheduler.py's existing account_for_strategy() lookup).
CHAMPION_SPECS: dict[str, tuple[int, tuple[str, ...]]] = {
    "core_h1": (3600, ("H4", "H1")),
    "champion_m30": (1800, ("H4", "H1", "M30")),
    "champion_h4": (14400, ("D1", "H4")),
    "champion_d1": (86400, ("D1",)),
}

# The three champions this module actually assigns/evaluates -- core_h1
# is excluded (see CHAMPION_SPECS' docstring above).
MANAGED_CHAMPIONS: tuple[str, ...] = ("champion_m30", "champion_h4", "champion_d1")


@dataclass(frozen=True)
class ChampionAssignment:
    account_id: str
    strategy_name: str
    params: dict
    assigned_at: str
    reason: str
    validation_summary: dict

    def build(self):
        cls = STRATEGY_CLASSES.get(self.strategy_name)
        if cls is None:
            raise ValueError(f"Unknown strategy name for champion assignment: {self.strategy_name!r}")
        return cls(**self.params)


def get_assignment(account_id: str) -> Optional[ChampionAssignment]:
    """None means this champion is currently unassigned -- a standing
    NO TRADE for every instrument at that timeframe, not an error."""
    if account_id not in MANAGED_CHAMPIONS:
        raise ValueError(f"Not a managed champion account: {account_id!r}")
    row = get_timeframe_champions().get(account_id)
    if not row:
        return None
    return ChampionAssignment(
        account_id=account_id,
        strategy_name=row["strategy_name"],
        params=row.get("params", {}),
        assigned_at=row["assigned_at"],
        reason=row.get("reason", ""),
        validation_summary=row.get("validation_summary", {}),
    )


def assign(account_id: str, strategy_name: str, params: dict, reason: str, validation_summary: dict) -> ChampionAssignment:
    """Replaces this champion's current strategy (or sets the first one).
    Every call is itself the audit trail entry -- prior assignments are
    kept in history, never silently dropped."""
    if account_id not in MANAGED_CHAMPIONS:
        raise ValueError(f"Not a managed champion account: {account_id!r}")
    if strategy_name not in STRATEGY_CLASSES:
        raise ValueError(f"Unknown strategy name: {strategy_name!r} (not in strategy_registry.STRATEGY_CLASSES)")

    champions = get_timeframe_champions()
    previous = champions.get(account_id)
    history = list(previous.get("history", [])) if previous else []
    if previous:
        history.append({k: previous[k] for k in ("strategy_name", "params", "assigned_at", "reason") if k in previous})

    row = {
        "strategy_name": strategy_name,
        "params": params,
        "assigned_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "validation_summary": validation_summary,
        "history": history,
    }
    champions[account_id] = row
    set_timeframe_champions(champions)
    return get_assignment(account_id)


def unassign(account_id: str, reason: str) -> None:
    """Explicit NO TRADE: clears the current strategy without picking a
    replacement (e.g. decay detected, no validated candidate ready yet)."""
    if account_id not in MANAGED_CHAMPIONS:
        raise ValueError(f"Not a managed champion account: {account_id!r}")
    champions = get_timeframe_champions()
    previous = champions.pop(account_id, None)
    if previous is not None:
        set_timeframe_champions(champions)

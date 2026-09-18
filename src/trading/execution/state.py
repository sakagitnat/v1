import copy
import json
from pathlib import Path
from typing import Optional

_STATE_PATH = Path(__file__).resolve().parents[3] / "state" / "bot_state.json"

_DEFAULTS = {
    "paused": False,
    "pause_reason": "",
    "capital_floor": None,
    "initial_floor": None,
    "milestone_reached": False,
    "excluded_symbols": {},
}


def load_state() -> dict:
    if not _STATE_PATH.exists():
        return copy.deepcopy(_DEFAULTS)
    state = json.loads(_STATE_PATH.read_text())
    for key, default in _DEFAULTS.items():
        state.setdefault(key, copy.deepcopy(default))
    return state


def _write_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def set_paused(paused: bool, reason: str = "") -> None:
    state = load_state()
    state["paused"] = paused
    state["pause_reason"] = reason if paused else ""
    _write_state(state)


def set_capital_floor(floor: Optional[float]) -> None:
    """Set (or, with None, clear) the equity floor: once account equity
    drops to or below this, the live bot stops opening new positions until
    equity recovers above it. See RiskManager.capital_floor / ladder.

    The first time a floor is set, it's also remembered as initial_floor
    (the original principal) so banked profit -- how much the ratchet has
    raised the floor by -- can be reported later. Clearing the floor
    (floor=None) leaves initial_floor alone.
    """
    state = load_state()
    state["capital_floor"] = floor
    if floor is not None and state.get("initial_floor") is None:
        state["initial_floor"] = floor
    _write_state(state)


def banked_profit(state: dict) -> float:
    """How much the capital floor has been ratcheted up by since it was
    first set -- i.e. how much profit is now protected/"locked in", not
    at risk of being traded away. 0 if no floor has ever been set."""
    floor = state.get("capital_floor")
    initial = state.get("initial_floor")
    if floor is None or initial is None:
        return 0.0
    return max(0.0, floor - initial)


def set_milestone_reached(reached: bool = True) -> None:
    """Marks that equity has crossed withdrawal_multiple x initial_floor at
    least once -- e.g. the $100 -> $200 "principal back + first $100 of
    usable profit" goal. From then on the live bot splits everything above
    the capital floor into buckets (safe / risk) instead of trading it all
    with one strategy. See buckets.py and Settings.withdrawal_multiple."""
    state = load_state()
    state["milestone_reached"] = reached
    _write_state(state)


def exclude_symbol(symbol: str, reason: str = "") -> None:
    """Block *new* entries into `symbol` (existing open positions are left
    alone -- their stop/target keep managing the exit) until explicitly
    re-included. Meant for a manual, judgment-based call -- e.g. reacting
    to news that's too fresh or too company-specific for a mechanical
    check like has_upcoming_earnings() to catch -- rather than anything
    the strategies compute themselves."""
    state = load_state()
    state.setdefault("excluded_symbols", {})[symbol.upper()] = reason
    _write_state(state)


def include_symbol(symbol: str) -> None:
    """Undo exclude_symbol: `symbol` becomes eligible for new entries again."""
    state = load_state()
    state.setdefault("excluded_symbols", {}).pop(symbol.upper(), None)
    _write_state(state)

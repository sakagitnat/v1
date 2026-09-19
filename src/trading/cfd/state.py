import copy
import json
from pathlib import Path
from typing import Optional

_STATE_PATH = Path(__file__).resolve().parents[3] / "state" / "cfd_bot_state.json"

_DEFAULTS = {
    "paused": False,
    "pause_reason": "",
    "capital_floor": None,
    "initial_floor": None,
    "excluded_instruments": {},
    "broker_equity_baseline": None,
    "virtual_starting_capital": None,
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
    state = load_state()
    state["capital_floor"] = floor
    if floor is not None and state.get("initial_floor") is None:
        state["initial_floor"] = floor
    _write_state(state)


def initialize_virtual_account(broker_equity: float, starting_capital: float) -> dict:
    """Persist the mapping from Deriv's forced demo balance to a virtual
    account. Existing values are preserved so repeated scheduler runs keep the
    same P&L history instead of silently rebasing after every run."""
    state = load_state()
    changed = False
    if state.get("broker_equity_baseline") is None:
        state["broker_equity_baseline"] = float(broker_equity)
        changed = True
    if state.get("virtual_starting_capital") is None:
        state["virtual_starting_capital"] = float(starting_capital)
        changed = True
    if changed:
        _write_state(state)
    return state


def virtual_equity_for_broker_equity(state: dict, broker_equity: float) -> float:
    baseline = state.get("broker_equity_baseline")
    starting = state.get("virtual_starting_capital")
    if baseline is None or starting is None:
        raise RuntimeError("Virtual account is not initialized")
    return float(starting) + (float(broker_equity) - float(baseline))


def exclude_instrument(instrument: str, reason: str = "") -> None:
    # Deriv symbol names are mixed-case and case-sensitive.
    state = load_state()
    state.setdefault("excluded_instruments", {})[instrument] = reason
    _write_state(state)


def include_instrument(instrument: str) -> None:
    state = load_state()
    state.setdefault("excluded_instruments", {}).pop(instrument, None)
    _write_state(state)

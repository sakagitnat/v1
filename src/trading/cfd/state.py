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


def exclude_instrument(instrument: str, reason: str = "") -> None:
    # Deliberately NOT .upper()'d: Deriv symbol names are mixed-case and
    # case-sensitive (frxXAUUSD, not FRXXAUUSD) -- uppercasing here would
    # silently break matching against settings.cfd_instruments in
    # scheduler.py, which checks `if instrument in excluded` using the
    # exact casing Deriv itself uses.
    state = load_state()
    state.setdefault("excluded_instruments", {})[instrument] = reason
    _write_state(state)


def include_instrument(instrument: str) -> None:
    state = load_state()
    state.setdefault("excluded_instruments", {}).pop(instrument, None)
    _write_state(state)

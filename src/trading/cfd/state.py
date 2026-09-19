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
    "broker_baseline": None,
    "open_trades": {},
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


def set_broker_baseline(balance: float) -> None:
    """Records the raw Deriv broker balance the first time this system
    ever sees the demo account -- the anchor trading.cfd.capital.
    virtual_equity() rebases every later balance onto the $100-scale
    virtual account. Deliberately set-once: called every run until a
    baseline exists, then a no-op forever after, so it can never drift
    once real (virtual) trading history depends on it."""
    state = load_state()
    if state.get("broker_baseline") is None:
        state["broker_baseline"] = balance
        _write_state(state)


def record_open_trade(contract_id: int, meta: dict) -> None:
    """Persists the entry-time details of a just-opened contract so a
    later run (a fresh process, on GitHub Actions) can still compute that
    trade's P&L and log it to the Trade Database once it closes -- see
    trading.cfd.trade_log and scheduler.py."""
    state = load_state()
    state.setdefault("open_trades", {})[str(contract_id)] = meta
    _write_state(state)


def pop_open_trade(contract_id: int) -> Optional[dict]:
    state = load_state()
    open_trades = state.setdefault("open_trades", {})
    meta = open_trades.pop(str(contract_id), None)
    _write_state(state)
    return meta


def list_open_trades() -> dict:
    return load_state().get("open_trades", {})


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

"""Local state for the XM/MT5 bot -- deliberately a separate file from
state.py (state/cfd_bot_state.json), not a shared one, so the MT5 bot
(scripts/run_mt5_service.py, running on the user's own Windows PC) can
never read or corrupt the Deriv bot's state (scripts/run_cfd_trading.py,
running on GitHub Actions), and vice versa, even though both happen to
share this same git repo and run in parallel.
"""
import copy
import json
from pathlib import Path
from typing import Optional

_STATE_PATH = Path(__file__).resolve().parents[3] / "state" / "mt5_bot_state.json"
_TRADE_LOG_PATH = Path(__file__).resolve().parents[3] / "state" / "mt5_trade_log.jsonl"

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
    state = load_state()
    state.setdefault("excluded_instruments", {})[instrument] = reason
    _write_state(state)


def include_instrument(instrument: str) -> None:
    state = load_state()
    state.setdefault("excluded_instruments", {}).pop(instrument, None)
    _write_state(state)


def append_trade_log(entry: dict) -> None:
    """Appends one JSON line per trade event (open/close) for later
    inspection -- e.g. by a local Claude Code session running on the same
    Windows PC while it's on (see docs/xm_mt5_setup.md)."""
    _TRADE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _TRADE_LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")

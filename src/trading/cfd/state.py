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
    "operating_mode": "normal",
    "operating_mode_reason": "",
    "paper_positions": {},
    "paper_equity": {},
    "paper_trade_counter": 0,
    "daily_risk_tracking": {"date": None, "start_equity": None, "halted": False},
    "pending_entries": {},
    "smoothed_equity": None,
    "high_water_mark": None,
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


def get_daily_risk_tracking() -> dict:
    """The daily-loss circuit breaker's state (UTC calendar date, that
    day's starting equity, and whether it's already halted today) --
    persisted here because trading.cfd.scheduler runs as a fresh process
    every ~hour (GitHub Actions), so CfdRiskManager's own in-memory
    _daily_start_equity/_halted would otherwise reset every single run
    and the "daily" loss limit would never actually accumulate loss
    across a real day. See scheduler.py's run_once() for how this gets
    fed into CfdRiskManager and written back after each run."""
    return load_state().get("daily_risk_tracking", {"date": None, "start_equity": None, "halted": False})


def set_daily_risk_tracking(date: str, start_equity: float, halted: bool) -> None:
    state = load_state()
    state["daily_risk_tracking"] = {"date": date, "start_equity": start_equity, "halted": halted}
    _write_state(state)


def get_equity_tracking() -> dict:
    """{"smoothed_equity": ..., "high_water_mark": ...} -- see
    trading.cfd.smoothed_equity. Both None until the first run ever
    records an observation. Persisted here for the same reason
    daily_risk_tracking is: trading.cfd.scheduler runs as a fresh
    process every ~hour (GitHub Actions), so an in-memory-only value
    would reset every single run."""
    state = load_state()
    return {"smoothed_equity": state.get("smoothed_equity"), "high_water_mark": state.get("high_water_mark")}


def set_equity_tracking(smoothed_equity: float, high_water_mark: float) -> None:
    state = load_state()
    state["smoothed_equity"] = smoothed_equity
    state["high_water_mark"] = high_water_mark
    _write_state(state)


def set_operating_mode(mode: str, reason: str = "") -> None:
    """Sets the CFD bot's operating mode (see trading.cfd.operating_mode
    for what each mode actually changes -- risk sizing tactics only,
    never whether the bot trades at all; use set_paused for that).
    Validated against operating_mode.VALID_MODES so a typo can never
    silently leave the bot running an unrecognized mode."""
    from trading.cfd.operating_mode import VALID_MODES

    if mode not in VALID_MODES:
        raise ValueError(f"Invalid operating mode {mode!r} -- must be one of {VALID_MODES}")
    state = load_state()
    state["operating_mode"] = mode
    state["operating_mode_reason"] = reason
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


def set_pending_entry(instrument: str, meta: dict) -> None:
    """Records intent to open a position on `instrument` BEFORE any order
    is actually submitted -- see trading.cfd.scheduler's Idempotency /
    Attribution recovery. If the process crashes between here and the
    matching clear_pending_entry() call (e.g. before the end-of-job git
    commit ever runs), the next run's reconciliation can tell a contract
    that appeared without local metadata apart from a genuinely foreign
    position: a stale pending entry names exactly what was about to be
    opened, so the attribution (strategy, thesis, risk_amount, ...)
    survives the crash instead of being lost. meta = {"legs": [per-leg
    dict, one or two, same shape record_open_trade() stores]}."""
    state = load_state()
    state.setdefault("pending_entries", {})[instrument] = meta
    _write_state(state)


def get_pending_entries() -> dict:
    return load_state().get("pending_entries", {})


def clear_pending_entry(instrument: str) -> None:
    state = load_state()
    state.setdefault("pending_entries", {}).pop(instrument, None)
    _write_state(state)


def next_paper_contract_id() -> int:
    """A synthetic, always-negative id for a paper trade -- see
    trading.cfd.paper_trading. Negative so it can never collide with a
    real Deriv contract_id (always a positive number from Deriv's own
    system), keeping paper and real trades unambiguous even if their
    records were ever compared side by side."""
    state = load_state()
    state["paper_trade_counter"] = state.get("paper_trade_counter", 0) + 1
    counter = state["paper_trade_counter"]
    _write_state(state)
    return -counter


def get_paper_equity(strategy_tag: str, default: float) -> float:
    return load_state().get("paper_equity", {}).get(strategy_tag, default)


def set_paper_equity(strategy_tag: str, equity: float) -> None:
    state = load_state()
    state.setdefault("paper_equity", {})[strategy_tag] = equity
    _write_state(state)


def get_paper_position(strategy_tag: str, instrument: str) -> Optional[dict]:
    return load_state().get("paper_positions", {}).get(f"{strategy_tag}|{instrument}")


def set_paper_position(strategy_tag: str, instrument: str, meta: dict) -> None:
    state = load_state()
    state.setdefault("paper_positions", {})[f"{strategy_tag}|{instrument}"] = meta
    _write_state(state)


def pop_paper_position(strategy_tag: str, instrument: str) -> Optional[dict]:
    state = load_state()
    positions = state.setdefault("paper_positions", {})
    meta = positions.pop(f"{strategy_tag}|{instrument}", None)
    _write_state(state)
    return meta


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

"""Strategy Registry -- src/trading/cfd/strategy_registry.py

Every CFD strategy candidate is a *version* of a *name*, tracked through
the lifecycle docs/VISION.md's "Strategy lifecycle" section defines:

    RESEARCH -> CANDIDATE -> VALIDATED -> PAPER -> ACTIVE -> PAUSED -> RETIRED

This is the registry, not the validation pipeline that's meant to gate
promotion through it (walk-forward, Monte Carlo/stress test, paper
trading -- see docs/ARCHITECTURE_AUDIT.md's later phases, not built yet).
For now, promotion is a deliberate, manual, audited action (set_state(),
exposed via `cfd_cli.py promote-strategy`) -- every transition is logged
with a reason, never a silent state flip.

Persisted to state/cfd_strategy_registry.json so lifecycle state survives
across GitHub Actions runs (each one is a fresh process, same pattern as
trading.cfd.state and trading.cfd.trade_log).
"""
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from trading.cfd.breakout import DonchianBreakoutStrategy
from trading.cfd.mean_reversion import MeanReversionStrategy
from trading.cfd.strategy import EmaCrossoverStrategy

_REGISTRY_PATH = Path(__file__).resolve().parents[3] / "state" / "cfd_strategy_registry.json"


class LifecycleState(str, Enum):
    RESEARCH = "RESEARCH"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    PAPER = "PAPER"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


# The order a strategy must earn one stage at a time via set_state() --
# RESEARCH first, ACTIVE last (PAUSED/RETIRED aren't "further" progress,
# just parking or ending -- handled separately in _valid_transition).
# register() can seed any initial state directly (see its docstring) --
# this ordering only gates transitions made *after* registration.
_FORWARD_ORDER = [
    LifecycleState.RESEARCH,
    LifecycleState.CANDIDATE,
    LifecycleState.VALIDATED,
    LifecycleState.PAPER,
    LifecycleState.ACTIVE,
]

# Strategy classes a registry entry's name can refer to. Both share the
# prepare()/signal_for_row() interface (trading.strategy.base.Signal), so
# the scheduler can run whichever the registry says is ACTIVE without
# caring which concrete class it is. Add a new strategy here the same run
# it's first registered.
STRATEGY_CLASSES = {
    "ema_crossover": EmaCrossoverStrategy,
    "donchian_breakout": DonchianBreakoutStrategy,
    "mean_reversion": MeanReversionStrategy,
}


@dataclass
class StrategyEntry:
    name: str
    version: str
    params: dict
    state: str
    created_at: str
    updated_at: str
    history: list = field(default_factory=list)
    """[{"from": ..., "to": ..., "reason": ..., "at": ...}, ...], oldest
    first, never truncated -- the audit trail that makes docs/VISION.md's
    "no hot-editing a live strategy without validation" rule checkable,
    not just assumed."""
    suited_regimes: list = field(default_factory=list)
    """Which trading.cfd.regime labels (e.g. "trending", "ranging") this
    strategy is meant to trade in -- trading.cfd.selector.select_for_entry
    matches the current regime against every ACTIVE entry's
    suited_regimes to decide what (if anything) trades an instrument this
    run. More than one ACTIVE entry may declare the same regime (see
    register()'s docstring); trading.cfd.portfolio_allocator weights risk
    across all of them and the selector picks among matches by that
    weight, not by "first one found." Empty by default -- an entry with
    no regimes declared is never selected for a new entry, rather than
    being treated as "suited to everything," so a strategy registered
    without this set explicitly can't accidentally start trading."""

    def build(self):
        """Instantiates the actual strategy object (EmaCrossoverStrategy,
        etc.) with this entry's registered params."""
        cls = STRATEGY_CLASSES.get(self.name)
        if cls is None:
            raise ValueError(f"Unknown strategy name in registry: {self.name!r} (not in STRATEGY_CLASSES)")
        return cls(**self.params)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_all() -> dict:
    if not _REGISTRY_PATH.exists():
        return {}
    return json.loads(_REGISTRY_PATH.read_text())


def _write_all(data: dict) -> None:
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY_PATH.write_text(json.dumps(data, indent=2) + "\n")


def _key(name: str, version: str) -> str:
    return f"{name}@{version}"


def register(
    name: str,
    version: str,
    params: dict,
    initial_state: LifecycleState = LifecycleState.RESEARCH,
    note: str = "",
    regimes: Optional[list[str]] = None,
) -> StrategyEntry:
    """Adds a new strategy version to the registry. Refuses to overwrite
    an existing (name, version) -- register a new version instead of
    mutating a registered one's params, so a version number always means
    exactly one fixed set of params (needed for the audit trail to mean
    anything: what was ACTUALLY live at a given time).

    initial_state defaults to RESEARCH (the normal starting point for a
    brand new candidate) but accepts any state directly -- used once, on
    purpose, to grandfather trading.cfd.strategy.EmaCrossoverStrategy
    straight into ACTIVE (see scripts/seed_strategy_registry.py) since it
    was already the live strategy before this registry existed. Every
    *later* transition goes through set_state(), which does enforce the
    pipeline order.

    Multiple ACTIVE entries may share overlapping suited_regimes -- per
    docs/VISION.md's revised "Portfolio / Allocation Decision" stage, this
    is a real portfolio manager, not a single-winner selector.
    trading.cfd.portfolio_allocator weights the risk budget across every
    ACTIVE strategy suited to a given regime, and trading.cfd.selector.
    select_for_entry() picks among them by that weight -- no ambiguity to
    guard against here."""
    data = _load_all()
    key = _key(name, version)
    if key in data:
        raise ValueError(f"{key} is already registered -- register a new version instead of overwriting one.")
    regimes = regimes or []
    entry = StrategyEntry(
        name=name,
        version=version,
        params=params,
        state=initial_state.value,
        created_at=_now_iso(),
        updated_at=_now_iso(),
        history=[{"from": None, "to": initial_state.value, "reason": note or "registered", "at": _now_iso()}],
        suited_regimes=regimes,
    )
    data[key] = asdict(entry)
    _write_all(data)
    return entry


def get(name: str, version: str) -> Optional[StrategyEntry]:
    raw = _load_all().get(_key(name, version))
    return StrategyEntry(**raw) if raw else None


def list_all() -> list[StrategyEntry]:
    return [StrategyEntry(**raw) for raw in _load_all().values()]


def list_by_state(state: LifecycleState) -> list[StrategyEntry]:
    return [e for e in list_all() if e.state == state.value]


def _valid_transition(from_state: LifecycleState, to_state: LifecycleState) -> bool:
    if to_state == LifecycleState.RETIRED:
        return from_state != LifecycleState.RETIRED  # terminal: reachable from anywhere else, nowhere back out
    if to_state == LifecycleState.PAUSED:
        return from_state == LifecycleState.ACTIVE
    if from_state == LifecycleState.PAUSED and to_state == LifecycleState.ACTIVE:
        return True  # resume
    if from_state in _FORWARD_ORDER and to_state in _FORWARD_ORDER:
        return _FORWARD_ORDER.index(to_state) == _FORWARD_ORDER.index(from_state) + 1
    return False


def set_state(name: str, version: str, to_state: LifecycleState, reason: str) -> StrategyEntry:
    """Transitions a registered strategy to a new lifecycle state.
    Enforces docs/VISION.md's pipeline order for forward progress (one
    stage at a time -- no skipping RESEARCH straight to ACTIVE), PAUSED
    only from/to ACTIVE, RETIRED from anywhere but never back out of it.

    reason is required: every promotion or demotion needs a stated
    justification recorded in the entry's history, not a bare state
    flip -- this is the "why" a future Failure Analysis or human review
    needs when asking "why was this strategy trading real money?".

    Promoting to ACTIVE no longer requires an exclusive regime -- several
    ACTIVE strategies may share suited_regimes at once (see register()'s
    docstring); trading.cfd.portfolio_allocator and trading.cfd.selector
    handle picking among them and weighting risk, not this registry."""
    if not reason:
        raise ValueError("set_state requires a non-empty reason -- every lifecycle change needs an audited justification.")
    data = _load_all()
    key = _key(name, version)
    raw = data.get(key)
    if raw is None:
        raise ValueError(f"{key} is not registered.")
    entry = StrategyEntry(**raw)
    from_state = LifecycleState(entry.state)
    if not _valid_transition(from_state, to_state):
        raise ValueError(f"Invalid transition {from_state.value} -> {to_state.value} for {key}.")
    entry.history.append({"from": from_state.value, "to": to_state.value, "reason": reason, "at": _now_iso()})
    entry.state = to_state.value
    entry.updated_at = _now_iso()
    data[key] = asdict(entry)
    _write_all(data)
    return entry

"""One-time seed: registers the two CFD strategies that already exist in
code (trading/cfd/strategy.py's EmaCrossoverStrategy, trading/cfd/
breakout.py's DonchianBreakoutStrategy) into the Strategy Registry
(trading/cfd/strategy_registry.py) -- see docs/VISION.md's "Strategy
lifecycle" section and docs/ARCHITECTURE_AUDIT.md's Phase 2.

Idempotent: skips any (name, version) already registered, so it's safe
to run again later (e.g. after adding a new strategy to this file)
without disturbing what's already there.

ema_crossover@v1 is seeded directly into ACTIVE -- a deliberate,
documented exception to the normal RESEARCH -> ... -> ACTIVE pipeline
set_state() enforces for every *future* promotion. It's simply already
the strategy the live scheduler has been trading (see cfd/scheduler.py's
history before this registry existed), backed by real TRAIN/TEST
validation (see README's "Backtesting" section for the numbers) -- just
never run through the newer formal registry/lifecycle machinery.
Grandfathered in, not a precedent for skipping stages going forward.

donchian_breakout@v1 was originally seeded into CANDIDATE with
breakout.py's own placeholder params (entry_window=30 etc. -- its
docstring always called these "not validated numbers"). Those were never
run through scripts/optimize_cfd_breakout.py; a separate grid search run
that session found a genuinely robust set of params instead (see v2
below) but never registered them -- an oversight only caught later by a
second, independent code review. v1 is retired here rather than left
sitting as a misleadingly-named "CANDIDATE" for params nobody was ever
going to test further; v2 carries the params that were actually
validated.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.strategy_registry import LifecycleState, get, register, set_state


def _seed(name: str, version: str, params: dict, state: LifecycleState, note: str, regimes: list) -> None:
    if get(name, version) is not None:
        print(f"{name}@{version} already registered -- skipping.")
        return
    register(name, version, params, initial_state=state, note=note, regimes=regimes)
    print(f"Registered {name}@{version} as {state.value} (suited_regimes={regimes}).")


def _retire_if_not_already(name: str, version: str, reason: str) -> None:
    entry = get(name, version)
    if entry is None or entry.state == LifecycleState.RETIRED.value:
        print(f"{name}@{version}: nothing to retire (missing or already retired) -- skipping.")
        return
    set_state(name, version, LifecycleState.RETIRED, reason=reason)
    print(f"Retired {name}@{version}.")


def main() -> None:
    # Both existing strategies are trend-following in nature -- see
    # trading.cfd.regime's docstring for why "trending" is the only
    # regime either is tagged for, and what happens (NO TRADE) in a
    # "ranging" one until a mean-reversion/range strategy joins the pool.
    _seed(
        "ema_crossover",
        "v1",
        {
            "fast_span": 15,
            "slow_span": 34,
            "atr_window": 14,
            "atr_stop_mult": 2.0,
            "atr_target_mult": 2.0,
            "adx_window": 14,
            "adx_threshold": 0.0,
        },
        LifecycleState.ACTIVE,
        "Grandfathered: already the live strategy before the registry existed; TRAIN/TEST-validated (see README).",
        regimes=["trending"],
    )
    _seed(
        "donchian_breakout",
        "v1",
        {
            "entry_window": 30,
            "exit_window": 10,
            "atr_window": 14,
            "atr_stop_mult": 2.5,
            "atr_target_mult": 4.0,
        },
        LifecycleState.CANDIDATE,
        "Implemented, not yet run through optimize_cfd_breakout.py's TRAIN/TEST validation.",
        regimes=["trending"],
    )
    _seed(
        "donchian_breakout",
        "v2",
        {
            "entry_window": 80,
            "exit_window": 15,
            "atr_window": 14,
            "atr_stop_mult": 3.5,
            "atr_target_mult": 6.0,
        },
        LifecycleState.VALIDATED,
        "The actual robust candidate found by optimize_cfd_breakout.py's grid search (TRAIN cagr=7.9% "
        "maxdd=-22.4%, TEST cagr=9.8% maxdd=-17.6% -- the first candidate all session, breakout or EMA "
        "crossover, where TRAIN and TEST agreed in both sign and rough magnitude; see scripts/"
        "sweep_cfd_risk_breakout.py's docstring and git commit d1a86d4 for the full numbers). Not yet run "
        "through trading.cfd.research_lab's walk-forward/Monte Carlo gate specifically -- registered as "
        "VALIDATED on the strength of this real TRAIN/TEST result, same grandfathering basis as "
        "ema_crossover@v1 above, not a claim that every later gate has been checked too.",
        regimes=["trending"],
    )
    _retire_if_not_already(
        "donchian_breakout",
        "v1",
        "Superseded by v2, registered with the parameters actually found and validated by "
        "optimize_cfd_breakout.py's grid search -- v1's params were always placeholders (see breakout.py's "
        "own docstring) and were never the ones tested.",
    )


if __name__ == "__main__":
    main()

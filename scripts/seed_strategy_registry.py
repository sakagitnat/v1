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

donchian_breakout@v1 is seeded into CANDIDATE -- implemented, but per its
own module docstring never run through scripts/optimize_cfd_breakout.py's
TRAIN/TEST validation yet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.strategy_registry import LifecycleState, get, register


def _seed(name: str, version: str, params: dict, state: LifecycleState, note: str, regimes: list) -> None:
    if get(name, version) is not None:
        print(f"{name}@{version} already registered -- skipping.")
        return
    register(name, version, params, initial_state=state, note=note, regimes=regimes)
    print(f"Registered {name}@{version} as {state.value} (suited_regimes={regimes}).")


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


if __name__ == "__main__":
    main()

"""Autonomous multi-strategy Research Lab driver --
scripts/research_cfd_strategies.py

Runs trading.cfd.research_lab's full auto-validation pipeline (Backtest
-> Out-of-Sample -> Walk-Forward -> Monte Carlo) against EVERY registered
strategy class's parameter grid in one pass, not just one strategy at a
time the way scripts/research_cfd_strategy.py (singular, donchian_breakout
only) does -- this is that idea generalized across the whole pool
(ema_crossover, donchian_breakout, mean_reversion, and anything added to
STRATEGY_SPECS below later), and the piece meant to run UNATTENDED on a
schedule (see .github/workflows/cfd-research.yml) rather than only when
someone remembers to trigger it by hand.

What "runs itself and improves itself" means here, precisely, and what it
does NOT mean:
  - It CAN, on its own, without a human in the loop: fetch fresh market
    history, grid-search a new parameter set for an existing strategy
    class, run it through the full walk-forward/Monte Carlo gate, and
    register a candidate that clears every gate as a new version in
    VALIDATED state -- exactly trading.cfd.research_lab.register_if_passed's
    own ceiling, never higher. A version that finds nothing is simply not
    registered (same as scripts/optimize_cfd_mean_reversion.py's honest
    negative result for mean_reversion@v1) -- never forced to look viable.
  - It can NEVER, under any circumstance, promote a candidate to PAPER or
    ACTIVE, touch CFD_ALLOW_LIVE_TRADING, or change any risk ceiling --
    those stay `cfd_cli.py promote-strategy`'s job, a deliberate, reasoned,
    human-typed command, per docs/VISION.md's "What the AI Trading Manager
    chooses vs. what it may never touch." A strategy this script registers
    sits at VALIDATED, exactly where a human-run optimize_cfd_*.py script's
    findings would sit if someone read the printed table and registered it
    by hand -- this script only removes the "someone has to remember to
    run it and type the registration command" step, not the human-decides-
    to-trade-it step.
  - It does NOT invent new strategy structures (no code generation) --
    "new candidate" means a new, systematically-searched parameter set for
    an EXISTING class in STRATEGY_SPECS below. A genuinely new structural
    idea (the way mean_reversion.py was a deliberate departure from
    trend-following) is still a design decision for a person (or Claude,
    asked) to make and add to STRATEGY_SPECS, not something this script
    conjures on its own.

Fetches each configured instrument's history ONCE and reuses it across
every strategy's grid search (three separate fetches would be wasteful --
they all want the same instruments/granularity/source today). Each
strategy's research pass is wrapped in try/except so one strategy's data
or logic problem can't take down the others' passes in the same run.

Needs a live network connection -- runs via .github/workflows/
cfd-research.yml on a weekly schedule, or on demand via that workflow's
workflow_dispatch, or the "CFD Manual Command" workflow's
research-strategies command.

Usage: python scripts/research_cfd_strategies.py [--granularity 3600] [--source deriv|yfinance]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.breakout import DonchianBreakoutStrategy
from trading.cfd.broker import DerivBroker
from trading.cfd.mean_reversion import MeanReversionStrategy
from trading.cfd.rsi_reversion import RsiReversionStrategy
from trading.cfd.research_lab import evaluate_candidate, generate_candidate_params, register_if_passed
from trading.cfd.strategy import EmaCrossoverStrategy
from trading.cfd.strategy_registry import list_all
from trading.config import settings

from optimize_cfd_breakout import PARAM_GRID as BREAKOUT_PARAM_GRID
from optimize_cfd_mean_reversion import PARAM_GRID as MEAN_REVERSION_PARAM_GRID
from optimize_cfd_rsi_reversion import PARAM_GRID as RSI_REVERSION_PARAM_GRID
from optimize_cfd_strategy import (
    MAX_DRAWDOWN_CAP,
    MIN_TRADES,
    PARAM_GRID as EMA_PARAM_GRID,
    TOP_N_TO_TEST,
    TRAIN_FRACTION,
    YFINANCE_INTERVAL_BY_GRANULARITY,
    calmar,
    fetch_history,
    fetch_history_yfinance,
    fmt,
    split,
)

# name -> (strategy class, its param grid, a structural filter_fn or None,
# the regimes a passing candidate gets registered under). Extend this,
# not the pipeline logic below, when a new strategy class is added to
# trading.cfd.strategy_registry.STRATEGY_CLASSES.
STRATEGY_SPECS = [
    {
        "name": "ema_crossover",
        "cls": EmaCrossoverStrategy,
        "param_grid": EMA_PARAM_GRID,
        "filter_fn": lambda c: c["fast_span"] < c["slow_span"],
        "suited_regimes": ["trending"],
    },
    {
        "name": "donchian_breakout",
        "cls": DonchianBreakoutStrategy,
        "param_grid": BREAKOUT_PARAM_GRID,
        "filter_fn": lambda c: c["entry_window"] > c["exit_window"],
        "suited_regimes": ["trending"],
    },
    {
        "name": "mean_reversion",
        "cls": MeanReversionStrategy,
        "param_grid": MEAN_REVERSION_PARAM_GRID,
        "filter_fn": None,
        "suited_regimes": ["ranging"],
    },
    {
        "name": "rsi_reversion",
        "cls": RsiReversionStrategy,
        "param_grid": RSI_REVERSION_PARAM_GRID,
        "filter_fn": None,
        "suited_regimes": ["ranging"],
    },
]


def run_backtest_full(cls, params: dict, bars: dict) -> dict:
    """Same shape as each optimize_cfd_*.py script's own run_backtest,
    generalized over the strategy class -- returns the FULL engine.run()
    result (trades + metrics), since Monte Carlo needs the trade-by-trade
    pnl list, not just the summary metrics."""
    strategy = cls(**params)
    engine = CfdBacktestEngine(
        strategy=strategy,
        starting_equity=10_000.0,
        risk_per_trade=settings.cfd_risk_per_trade,
        max_open_positions=settings.cfd_max_open_positions,
        max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
        spread_pct=settings.cfd_backtest_spread_pct,
        daily_financing_pct=settings.cfd_backtest_daily_financing_pct,
    )
    return engine.run(bars)


def research_one_strategy(spec: dict, train_bars: dict, test_bars: dict) -> dict:
    """Runs the full two-stage pipeline for one strategy spec (cheap
    TRAIN-only filter+rank, then the full Research Lab gate on the
    survivors) and registers whatever clears it. Returns a small summary
    dict for the run's final report -- never raises: a strategy that
    fails to research cleanly (bad data, an unexpected exception) is
    reported as an error and skipped, not allowed to abort every other
    strategy's pass in the same run."""
    name = spec["name"]
    cls = spec["cls"]
    try:
        baseline_test = run_backtest_full(cls, {}, test_bars)["metrics"]
        candidates = generate_candidate_params(spec["param_grid"], filter_fn=spec["filter_fn"])
        print(f"\n=== {name}: searching {len(candidates)} parameter combinations on TRAIN ===")

        ranked = []
        for params in candidates:
            m = run_backtest_full(cls, params, train_bars)["metrics"]
            if m["num_trades"] < MIN_TRADES or m["cagr_pct"] <= 0 or m["max_drawdown_pct"] < MAX_DRAWDOWN_CAP:
                continue
            ranked.append((params, m))
        ranked.sort(key=lambda r: calmar(r[1]), reverse=True)
        print(f"  {len(ranked)}/{len(candidates)} cleared the cheap TRAIN gate.")

        if not ranked:
            return {"name": name, "registered": [], "note": "nothing cleared even the cheap TRAIN gate"}

        top = ranked[:TOP_N_TO_TEST]
        existing_versions = {e.version for e in list_all() if e.name == name}
        next_version_num = len(existing_versions) + 1

        registered = []
        for params, _train_m in top:
            report = evaluate_candidate(lambda p, b, _cls=cls: run_backtest_full(_cls, p, b), train_bars, test_bars, params, baseline_test)
            if not report.passed:
                print(f"  rejected {params}: {report.reasons}")
                continue
            version = f"v{next_version_num}"
            next_version_num += 1
            register_if_passed(name, version, report, regimes=spec["suited_regimes"])
            registered.append(version)
            print(f"  PASSED -> registered {name}@{version} as VALIDATED: {params}")
            print(f"    TRAIN {fmt(report.train_metrics)}")
            print(f"    TEST  {fmt(report.test_metrics)}")
            print(
                f"    walk-forward: {report.walk_forward['profitable_folds']}/{report.walk_forward['n_folds']} "
                f"folds profitable, worst drawdown {report.walk_forward['worst_drawdown_pct']}%"
            )
            print(f"    Monte Carlo ruin probability: {report.monte_carlo['ruin_probability_pct']}%")

        note = "" if registered else "no candidate cleared the full walk-forward/Monte Carlo gate"
        return {"name": name, "registered": registered, "note": note}
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: one strategy's failure must not abort the others
        print(f"  ERROR researching {name}: {exc!r} -- skipping this strategy for this run.")
        return {"name": name, "registered": [], "note": f"error: {exc!r}"}


async def main(granularity_seconds: int, source: str):
    bars = {}
    if source == "deriv":
        broker = DerivBroker()
        try:
            await broker.connect()
            for instrument in settings.cfd_instruments:
                print(f"Fetching {instrument} history ({granularity_seconds}s bars)...")
                bars[instrument] = await fetch_history(broker, instrument, granularity_seconds)
        finally:
            await broker.close()
    else:
        interval = YFINANCE_INTERVAL_BY_GRANULARITY.get(granularity_seconds, "1h")
        print(f"Fetching from yfinance (interval={interval}, a proxy feed -- see optimize_cfd_strategy.py's docstring)...")
        for instrument in settings.cfd_instruments:
            bars[instrument] = fetch_history_yfinance(instrument, interval)

    bars = {sym: df for sym, df in bars.items() if not df.empty}
    if not bars:
        print("No history fetched for any instrument -- aborting.")
        return

    train_bars, test_bars = split(bars)
    train_start = min(df.index[0] for df in train_bars.values() if not df.empty)
    test_end = max(df.index[-1] for df in test_bars.values() if not df.empty)
    print(f"History: {train_start} to {test_end} ({TRAIN_FRACTION:.0%} TRAIN / {1 - TRAIN_FRACTION:.0%} TEST per instrument)")
    print(f"Researching {len(STRATEGY_SPECS)} strategies: {', '.join(s['name'] for s in STRATEGY_SPECS)}")

    results = [research_one_strategy(spec, train_bars, test_bars) for spec in STRATEGY_SPECS]

    print("\n=== Summary ===")
    any_registered = False
    for r in results:
        if r["registered"]:
            any_registered = True
            print(f"  {r['name']}: registered {', '.join(r['registered'])} as VALIDATED")
        else:
            print(f"  {r['name']}: nothing registered ({r['note']})")
    if any_registered:
        print(
            "\nNew VALIDATED candidate(s) above are NOT trading -- promotion to PAPER/ACTIVE is still a deliberate "
            "`cfd_cli.py promote-strategy` decision. Run `cfd_cli.py list-strategies` to review them."
        )
    else:
        print("\nNo new candidates this run. Existing registry unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    parser.add_argument("--source", choices=["deriv", "yfinance"], default="yfinance")
    args = parser.parse_args()
    asyncio.run(main(args.granularity, args.source))

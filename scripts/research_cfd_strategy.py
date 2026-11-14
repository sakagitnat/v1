"""Runs the Research Lab's full auto-validation pipeline (Backtest ->
Out-of-Sample -> Walk-Forward -> Monte Carlo) against
DonchianBreakoutStrategy's parameter grid, and auto-registers any
candidate that clears every gate into the Strategy Registry as VALIDATED
-- see trading.cfd.research_lab's docstring for exactly what "passes"
means and why VALIDATED, never higher, is as far as this goes
automatically. Promoting further (PAPER, then ACTIVE) is still a
deliberate, manual `cfd_cli.py promote-strategy` decision.

Reuses scripts/optimize_cfd_breakout.py's own data-fetch, grid, and
backtest-runner code (same PARAM_GRID, same TRAIN/TEST split, same
history sources) instead of duplicating it -- this script's value-add is
running Walk-Forward + Monte Carlo on top of that same search, and
registering a result instead of only printing one. Two stages, same
discipline as optimize_cfd_breakout.py: first a cheap TRAIN-only metrics
filter+rank (no walk-forward/Monte Carlo yet) to find the top
TOP_N_TO_TEST candidates, then the full (much more expensive) Research
Lab pipeline only on those -- evaluating every grid combination through
1000-simulation Monte Carlo would be needless compute for the combinations
that don't even clear the cheap TRAIN gate.

Needs a live network connection -- run via the "CFD Manual Command"
GitHub Actions workflow and read its job logs.

Usage: python scripts/research_cfd_strategy.py [--granularity 3600] [--source deriv|yfinance]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.breakout import DonchianBreakoutStrategy
from trading.cfd.broker import DerivBroker
from trading.cfd.research_lab import evaluate_candidate, generate_candidate_params, register_if_passed
from trading.cfd.strategy_registry import list_all
from trading.config import settings

from optimize_cfd_breakout import PARAM_GRID
from optimize_cfd_strategy import (
    MAX_DRAWDOWN_CAP,
    MIN_TRADES,
    TOP_N_TO_TEST,
    TRAIN_FRACTION,
    YFINANCE_INTERVAL_BY_GRANULARITY,
    calmar,
    fetch_history,
    fetch_history_yfinance,
    fmt,
    split,
)

STRATEGY_NAME = "donchian_breakout"
SUITED_REGIMES = ["trending"]  # same trend-following classification as ema_crossover -- see trading.cfd.regime


def run_backtest_full(params: dict, bars: dict) -> dict:
    """Same shape as optimize_cfd_breakout.run_backtest, but returns the
    FULL engine.run() result (trades + metrics), not just metrics --
    Monte Carlo needs the trade-by-trade pnl list."""
    strategy = DonchianBreakoutStrategy(**params)
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
    print(f"\nTRAIN: {TRAIN_FRACTION:.0%} of fetched bars per instrument, TEST: the rest")

    baseline_test = run_backtest_full({}, test_bars)["metrics"]
    print(f"Baseline (default params) TEST: {fmt(baseline_test)}")

    candidates = generate_candidate_params(
        PARAM_GRID, filter_fn=lambda c: c["entry_window"] > c["exit_window"]
    )
    print(f"\nStage 1: cheap TRAIN-only ranking of {len(candidates)} candidates...")
    ranked = []
    for params in candidates:
        m = run_backtest_full(params, train_bars)["metrics"]
        if m["num_trades"] < MIN_TRADES or m["cagr_pct"] <= 0 or m["max_drawdown_pct"] < MAX_DRAWDOWN_CAP:
            continue
        ranked.append((params, m))
    ranked.sort(key=lambda r: calmar(r[1]), reverse=True)
    print(f"  {len(ranked)}/{len(candidates)} cleared the cheap TRAIN gate.")

    if not ranked:
        print("\nNo candidate cleared even the cheap TRAIN gate -- nothing to run the full pipeline on.")
        return

    top = ranked[:TOP_N_TO_TEST]
    print(f"\nStage 2: full Research Lab pipeline (TEST + walk-forward + Monte Carlo) on the top {len(top)}...")
    existing_versions = {e.version for e in list_all() if e.name == STRATEGY_NAME}
    next_version_num = len(existing_versions) + 1

    passed_any = False
    for params, train_m in top:
        report = evaluate_candidate(run_backtest_full, train_bars, test_bars, params, baseline_test)
        if report.passed:
            version = f"v{next_version_num}"
            next_version_num += 1
            register_if_passed(STRATEGY_NAME, version, report, regimes=SUITED_REGIMES)
            passed_any = True
            print(f"\nPASSED -> registered {STRATEGY_NAME}@{version} as VALIDATED: {params}")
            print(f"  TRAIN {fmt(report.train_metrics)}")
            print(f"  TEST  {fmt(report.test_metrics)}")
            print(f"  walk-forward: {report.walk_forward['profitable_folds']}/{report.walk_forward['n_folds']} folds profitable, worst drawdown {report.walk_forward['worst_drawdown_pct']}%")
            print(f"  Monte Carlo: ruin probability {report.monte_carlo['ruin_probability_pct']}%, final equity p5/p50/p95 = {report.monte_carlo['final_equity_p5']}/{report.monte_carlo['final_equity_p50']}/{report.monte_carlo['final_equity_p95']}")
        else:
            print(f"\nrejected {params}: {report.reasons}")

    if not passed_any:
        print(f"\nNone of the top {len(top)} candidates cleared every gate -- nothing registered. See `cfd_cli.py list-strategies`.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    parser.add_argument("--source", choices=["deriv", "yfinance"], default="yfinance")
    args = parser.parse_args()
    asyncio.run(main(args.granularity, args.source))

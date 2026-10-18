"""Research/validate VolatilityExpansionBreakoutStrategy.

Pipeline:
1) Fetch H1 forex/gold history.
2) Cheap TRAIN gate across a bounded parameter grid.
3) Evaluate top candidates on untouched TEST.
4) Walk-forward + Monte Carlo via trading.cfd.research_lab.
5) Register passing candidates as VALIDATED only. Never PAPER/ACTIVE.

Usage:
  python scripts/research_cfd_volatility_expansion.py --granularity 3600 --source yfinance
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.broker import DerivBroker
from trading.cfd.research_lab import evaluate_candidate, generate_candidate_params, register_if_passed
from trading.cfd.strategy_registry import list_all
from trading.cfd.volatility_expansion import VolatilityExpansionBreakoutStrategy
from trading.config import settings

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

STRATEGY_NAME = "volatility_expansion"
SUITED_REGIMES = ["ranging", "trending"]

PARAM_GRID = {
    "channel_window": [12, 20, 30],
    "compression_quantile": [0.15, 0.25],
    "atr_expansion_mult": [1.05, 1.15],
    "atr_stop_mult": [1.5, 2.5],
    "atr_target_mult": [2.5, 4.0],
}


def run_backtest_full(params: dict, bars: dict) -> dict:
    strategy = VolatilityExpansionBreakoutStrategy(**params)
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
        print(f"Fetching yfinance proxy history (interval={interval})...")
        for instrument in settings.cfd_instruments:
            bars[instrument] = fetch_history_yfinance(instrument, interval)

    bars = {sym: df for sym, df in bars.items() if not df.empty}
    if not bars:
        raise SystemExit("No history fetched for any instrument.")

    train_bars, test_bars = split(bars)
    print(f"TRAIN={TRAIN_FRACTION:.0%}, TEST={1-TRAIN_FRACTION:.0%}")

    baseline_test = run_backtest_full({}, test_bars)["metrics"]
    print(f"Baseline TEST: {fmt(baseline_test)}")

    candidates = generate_candidate_params(PARAM_GRID)
    print(f"Stage 1: {len(candidates)} candidates on TRAIN")
    ranked = []
    for params in candidates:
        metrics = run_backtest_full(params, train_bars)["metrics"]
        if (
            metrics["num_trades"] >= MIN_TRADES
            and metrics["cagr_pct"] > 0
            and metrics["max_drawdown_pct"] >= MAX_DRAWDOWN_CAP
        ):
            ranked.append((params, metrics))
    ranked.sort(key=lambda x: calmar(x[1]), reverse=True)
    print(f"{len(ranked)}/{len(candidates)} cleared TRAIN gate.")

    if not ranked:
        print("NEGATIVE RESULT: no candidate cleared TRAIN gate. Nothing registered.")
        return

    existing_versions = {e.version for e in list_all() if e.name == STRATEGY_NAME}
    next_version_num = max(
        [int(v[1:]) for v in existing_versions if v.startswith("v") and v[1:].isdigit()] or [0]
    ) + 1

    passed = []
    for params, train_metrics in ranked[:TOP_N_TO_TEST]:
        report = evaluate_candidate(
            run_backtest_full,
            train_bars,
            test_bars,
            params,
            baseline_test,
        )
        print(f"Candidate {params}")
        print(f"  TRAIN {fmt(train_metrics)}")
        print(f"  TEST  {fmt(report.test_metrics)}")
        if not report.passed:
            print(f"  REJECTED: {report.reasons}")
            continue
        version = f"v{next_version_num}"
        next_version_num += 1
        register_if_passed(STRATEGY_NAME, version, report, regimes=SUITED_REGIMES)
        passed.append((version, params, report))
        print(f"  PASSED -> {STRATEGY_NAME}@{version} VALIDATED")

    if not passed:
        print("NEGATIVE RESULT: no top candidate cleared TEST + walk-forward + Monte Carlo. Nothing registered.")
        return

    print("\n=== VALIDATED RESULTS ===")
    for version, params, report in passed:
        print(f"{STRATEGY_NAME}@{version}: {params}")
        print(f"  TRAIN {fmt(report.train_metrics)}")
        print(f"  TEST  {fmt(report.test_metrics)}")
        print(f"  walk-forward consistency={report.walk_forward['consistency_pct']}%")
        print(f"  Monte Carlo ruin={report.monte_carlo['ruin_probability_pct']}%")
    print("No candidate was promoted to PAPER or ACTIVE.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    parser.add_argument("--source", choices=["deriv", "yfinance"], default="yfinance")
    args = parser.parse_args()
    asyncio.run(main(args.granularity, args.source))

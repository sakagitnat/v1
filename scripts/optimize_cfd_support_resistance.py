"""Grid-search SupportResistanceReversionStrategy's parameters against
real forex/gold history, using the same TRAIN/TEST/overfit-safety
discipline as optimize_cfd_mean_reversion.py and
optimize_cfd_rsi_reversion.py.

Support/resistance reversion is structurally distinct from both prior
ranging-regime attempts: mean_reversion@v1 (retired) and rsi_reversion@v1
(retired) both faded a derived statistic over closes (a Bollinger Band,
an RSI oscillator) -- this strategy instead reads confirmed swing-high/
swing-low price structure, a genuinely different data representation,
not just a different formula over the same input. See GitHub issue #5
for the full reasoning behind picking this as the third candidate.

Needs a live network connection -- run via GitHub Actions and inspect
the job logs.

Usage: python scripts/optimize_cfd_support_resistance.py [--granularity 3600] [--source deriv|yfinance]
"""
import argparse
import asyncio
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.broker import DerivBroker
from trading.cfd.support_resistance import SupportResistanceReversionStrategy
from trading.config import settings

from optimize_cfd_strategy import (
    CHUNKS_PER_INSTRUMENT,
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

PARAM_GRID = {
    "pivot_window": [3, 5, 8],
    "touch_threshold_pct": [0.0005, 0.001, 0.002],
    "atr_stop_mult": [1.0, 1.5, 2.5],
    "atr_target_mult": [1.5, 2.5, 4.0],
}


def run_backtest(strategy_kwargs: dict, bars: dict) -> dict:
    strategy = SupportResistanceReversionStrategy(**strategy_kwargs)
    engine = CfdBacktestEngine(
        strategy=strategy,
        starting_equity=10_000.0,
        risk_per_trade=settings.cfd_risk_per_trade,
        max_open_positions=settings.cfd_max_open_positions,
        max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
        spread_pct=settings.cfd_backtest_spread_pct,
        daily_financing_pct=settings.cfd_backtest_daily_financing_pct,
    )
    return engine.run(bars)["metrics"]


async def main(granularity_seconds: int, source: str):
    bars = {}
    if source == "deriv":
        broker = DerivBroker()
        try:
            await broker.connect()
            for instrument in settings.cfd_instruments:
                print(f"Fetching {instrument} history ({granularity_seconds}s bars, up to {CHUNKS_PER_INSTRUMENT} chunks)...")
                df = await fetch_history(broker, instrument, granularity_seconds)
                span = f"{df.index[0]} to {df.index[-1]}" if not df.empty else "no data"
                print(f"  total: {len(df)} bars, {span}")
                bars[instrument] = df
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
    train_end = max(df.index[-1] for df in train_bars.values() if not df.empty)
    test_start = min(df.index[0] for df in test_bars.values() if not df.empty)
    test_end = max(df.index[-1] for df in test_bars.values() if not df.empty)
    print(f"\nTRAIN: {train_start} to {train_end} ({TRAIN_FRACTION:.0%} of fetched bars per instrument)")
    print(f"TEST:  {test_start} to {test_end}")

    baseline_train = run_backtest({}, train_bars)
    baseline_test = run_backtest({}, test_bars)
    print("\nBaseline (SupportResistanceReversionStrategy default params, unvalidated placeholders):")
    print(f"  TRAIN {fmt(baseline_train)}")
    print(f"  TEST  {fmt(baseline_test)}")

    keys = list(PARAM_GRID.keys())
    combos = [dict(zip(keys, values)) for values in itertools.product(*PARAM_GRID.values())]
    print(f"\nSearching {len(combos)} parameter combinations on TRAIN...")

    results = []
    for kwargs in combos:
        m = run_backtest(kwargs, train_bars)
        if m["num_trades"] < MIN_TRADES:
            continue
        results.append((kwargs, m))

    pool = [r for r in results if r[1]["cagr_pct"] > 0 and r[1]["max_drawdown_pct"] >= MAX_DRAWDOWN_CAP]
    pool.sort(key=lambda r: calmar(r[1]), reverse=True)
    print(
        f"\nTop {TOP_N_TO_TEST} by TRAIN calmar (cagr/|maxdd|) among combos with CAGR > 0 "
        f"and drawdown no worse than {MAX_DRAWDOWN_CAP}% ({len(pool)}/{len(results)} qualify):"
    )
    for kwargs, m in pool[:TOP_N_TO_TEST]:
        print(f"  calmar={calmar(m):.2f}  {kwargs} -> {fmt(m)}")

    if not pool:
        print(f"\nNo combination qualified (min {MIN_TRADES} trades, CAGR>0, drawdown cap). SupportResistanceReversionStrategy does not look promising on this data.")
        return

    print(f"\nEvaluating top {min(TOP_N_TO_TEST, len(pool))} TRAIN candidates on TEST...")
    robust = []
    for kwargs, train_m in pool[:TOP_N_TO_TEST]:
        test_m = run_backtest(kwargs, test_bars)
        overfit = test_m["cagr_pct"] <= 0 or test_m["max_drawdown_pct"] < MAX_DRAWDOWN_CAP
        underperforms_baseline = test_m["cagr_pct"] < baseline_test["cagr_pct"]
        verdict = "OVERFIT" if overfit else ("UNDERPERFORMS BASELINE" if underperforms_baseline else "ROBUST")
        print(f"  {kwargs}\n    TRAIN {fmt(train_m)}\n    TEST  {fmt(test_m)}  [{verdict}]")
        if not overfit and not underperforms_baseline:
            robust.append((kwargs, train_m, test_m))

    if not robust:
        print(
            "\n  None of the top candidates hold up out-of-sample and beat the baseline on TEST. "
            "SupportResistanceReversionStrategy does not look promising on this data either."
        )
        return

    robust.sort(key=lambda r: calmar(r[2]), reverse=True)
    best_kwargs, best_train, best_test = robust[0]
    print(f"\n=== Best robust candidate: {best_kwargs} ===")
    print(f"  TRAIN {fmt(best_train)}")
    print(f"  TEST  {fmt(best_test)}")
    print("\n  Holds up out-of-sample and beats the baseline on TEST.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    parser.add_argument("--source", choices=["deriv", "yfinance"], default="yfinance")
    args = parser.parse_args()
    asyncio.run(main(args.granularity, args.source))

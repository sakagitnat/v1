"""Grid-search LondonBreakoutStrategy's parameters against real
forex/gold history -- same TRAIN/TEST/Deflated-Sharpe discipline as
optimize_cfd_strategy.py (see that file's docstring for the full
methodology; reused here via import, not copy-pasted).

Why this strategy: a genuinely different structural bet from the two
already in this project's pool. EmaCrossoverStrategy and
DonchianBreakoutStrategy are both "what has price just done" signals
with no concept of time of day; LondonBreakoutStrategy's edge
hypothesis is specifically that the Asian session's tighter range gets
broken decisively once London desks open -- a well-known FX seasonality
pattern external research surfaced (see docs/DECISIONS.md), not
previously represented here. See trading.cfd.london_breakout's
docstring for the exact mechanics.

Needs a live network connection -- run via the "CFD Manual Command"
GitHub Actions workflow (command=optimize-london-breakout) and read its
job logs.

Usage: python scripts/optimize_cfd_london_breakout.py [--granularity 3600] [--source deriv|yfinance]
"""
import argparse
import asyncio
import itertools
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker
from trading.cfd.deflated_sharpe import annualized_to_per_period
from trading.cfd.london_breakout import LondonBreakoutStrategy
from trading.config import settings

from optimize_cfd_strategy import (
    CHUNKS_PER_INSTRUMENT,
    MAX_DRAWDOWN_CAP,
    MIN_TRADES,
    TOP_N_TO_TEST,
    TRAIN_FRACTION,
    YFINANCE_INTERVAL_BY_GRANULARITY,
    _periods_per_year,
    calmar,
    fetch_history,
    fetch_history_yfinance,
    fmt,
    report_dsr,
    run_backtest,
    run_backtest_full,
    split,
)

PARAM_GRID = {
    # Asian-session window and London breakout window both widened
    # around the reasonable-placeholder defaults (00:00-07:00 Asian,
    # 07:00-10:00 breakout) rather than assumed correct -- different
    # desks/sources draw the Asian session's boundaries differently, and
    # this is exactly the kind of threshold this project never ships
    # unvalidated (see strategy.py's ADX chop filter for the same
    # discipline applied elsewhere).
    "asian_end_hour": [6, 7, 8],
    "breakout_end_hour": [9, 10, 12],
    "session_close_hour": [16, 18, 20],
    "atr_stop_mult": [1.0, 1.5, 2.5],
    "atr_target_mult": [2.0, 3.0, 4.5],
}


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

    baseline_train_full = run_backtest_full({}, train_bars, LondonBreakoutStrategy)
    baseline_train = baseline_train_full["metrics"]
    baseline_test = run_backtest({}, test_bars, LondonBreakoutStrategy)
    print("\nBaseline (LondonBreakoutStrategy default params, unvalidated placeholders):")
    print(f"  TRAIN {fmt(baseline_train)}")
    print(f"  TEST  {fmt(baseline_test)}")

    periods_per_year = _periods_per_year(baseline_train_full["equity_curve"])

    keys = list(PARAM_GRID.keys())
    combos = [
        dict(zip(keys, values))
        for values in itertools.product(*PARAM_GRID.values())
        if values[0] < values[1] <= values[2]  # asian_end < breakout_end <= session_close, or the windows are nonsensical
    ]
    print(f"\nSearching {len(combos)} parameter combinations on TRAIN...")

    results = []
    for kwargs in combos:
        m = run_backtest(kwargs, train_bars, LondonBreakoutStrategy)
        if m["num_trades"] < MIN_TRADES:
            continue
        results.append((kwargs, m))

    trial_sharpes_per_period = [annualized_to_per_period(m["sharpe_ratio"], periods_per_year) for _, m in results]
    sr_std_per_period = statistics.pstdev(trial_sharpes_per_period) if len(trial_sharpes_per_period) >= 2 else 0.0

    pool = [r for r in results if r[1]["cagr_pct"] > 0 and r[1]["max_drawdown_pct"] >= MAX_DRAWDOWN_CAP]
    pool.sort(key=lambda r: calmar(r[1]), reverse=True)
    print(
        f"\nTop {TOP_N_TO_TEST} by TRAIN calmar (cagr/|maxdd|) among combos with CAGR > 0 "
        f"and drawdown no worse than {MAX_DRAWDOWN_CAP}% ({len(pool)}/{len(results)} qualify):"
    )
    for kwargs, m in pool[:TOP_N_TO_TEST]:
        print(f"  calmar={calmar(m):.2f}  {kwargs} -> {fmt(m)}")

    if not pool:
        print(
            f"\nNo combination qualified (min {MIN_TRADES} trades, CAGR>0, drawdown cap). "
            "LondonBreakoutStrategy does not look promising on this data."
        )
        report_dsr("baseline (kept)", {}, train_bars, sr_std_per_period, len(combos), LondonBreakoutStrategy)
        return

    print(f"\nEvaluating top {min(TOP_N_TO_TEST, len(pool))} TRAIN candidates on TEST...")
    robust = []
    for kwargs, train_m in pool[:TOP_N_TO_TEST]:
        test_m = run_backtest(kwargs, test_bars, LondonBreakoutStrategy)
        overfit = test_m["cagr_pct"] <= 0 or test_m["max_drawdown_pct"] < MAX_DRAWDOWN_CAP
        underperforms_baseline = test_m["cagr_pct"] < baseline_test["cagr_pct"]
        verdict = "OVERFIT" if overfit else ("UNDERPERFORMS BASELINE" if underperforms_baseline else "ROBUST")
        print(f"  {kwargs}\n    TRAIN {fmt(train_m)}\n    TEST  {fmt(test_m)}  [{verdict}]")
        if not overfit and not underperforms_baseline:
            robust.append((kwargs, train_m, test_m))

    if not robust:
        print(
            "\n  None of the top candidates hold up out-of-sample and beat the baseline on TEST. "
            "LondonBreakoutStrategy does not look promising on this data either."
        )
        report_dsr("baseline (kept)", {}, train_bars, sr_std_per_period, len(combos), LondonBreakoutStrategy)
        return

    robust.sort(key=lambda r: calmar(r[2]), reverse=True)
    best_kwargs, best_train, best_test = robust[0]
    print(f"\n=== Best robust candidate: {best_kwargs} ===")
    print(f"  TRAIN {fmt(best_train)}")
    print(f"  TEST  {fmt(best_test)}")
    print("\n  Holds up out-of-sample and beats the baseline on TEST.")
    report_dsr("recommended candidate", best_kwargs, train_bars, sr_std_per_period, len(combos), LondonBreakoutStrategy)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    parser.add_argument("--source", choices=["deriv", "yfinance"], default="yfinance")
    args = parser.parse_args()
    asyncio.run(main(args.granularity, args.source))

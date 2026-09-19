"""Grid-search EmaCrossoverStrategy's parameters against real Deriv
history, validated out-of-sample -- the CFD/forex counterpart of
scripts/optimize_strategy.py, same discipline: history splits into a
TRAIN period (the grid search runs here) and a TEST/holdout period
touched only once at the end, as a sanity check against curve-fitting.
Any combo whose TRAIN max drawdown breaches MAX_DRAWDOWN_CAP is rejected
outright, however good its return -- "the portfolio must not blow up"
stays a hard constraint, not something the search can trade away for a
better number.

Backtests all configured instruments together, sharing one
CfdRiskManager -- matching how the live scheduler actually trades them
(shared max_open_positions, shared daily-loss circuit breaker), not as
independent single-instrument backtests.

Needs a live Deriv connection to fetch candle history (this sandbox has
no network access to Deriv) -- run via the "CFD Manual Command" GitHub
Actions workflow (command=optimize-strategy) and read its job logs.

Usage: python scripts/optimize_cfd_strategy.py
"""
import asyncio
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.broker import DerivBroker
from trading.cfd.strategy import EmaCrossoverStrategy
from trading.config import settings

GRANULARITY_SECONDS = 900  # 15 minutes, matches scheduler.py
CHUNK_COUNT = 5000  # Deriv's approx per-request cap for ticks_history
CHUNKS_PER_INSTRUMENT = 8  # ~8 * 5000 M15 bars -- roughly 1.5-2 years of 24/5 forex/gold history

TRAIN_FRACTION = 0.7  # proportional, not fixed calendar dates -- history depth isn't known ahead of a live fetch
MIN_TRADES = 20  # ignore combos too thin to trust their metrics
MAX_DRAWDOWN_CAP = -25.0  # reject any combo whose TRAIN max drawdown is worse than this

PARAM_GRID = {
    "fast_span": [8, 12, 16],
    "slow_span": [21, 26, 34],
    "atr_stop_mult": [1.0, 1.5, 2.0],
    "atr_target_mult": [1.5, 2.5, 3.5],
}


async def fetch_history(broker: DerivBroker, symbol: str) -> pd.DataFrame:
    chunks = []
    end: str | int = "latest"
    for _ in range(CHUNKS_PER_INSTRUMENT):
        bars = await broker.get_candles(symbol, granularity_seconds=GRANULARITY_SECONDS, count=CHUNK_COUNT, end=end)
        if bars.empty:
            break
        chunks.append(bars)
        oldest_epoch = int(bars.index[0].timestamp())
        next_end = oldest_epoch - GRANULARITY_SECONDS
        if next_end == end:  # no progress -- hit the start of available history
            break
        end = next_end
    if not chunks:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    combined = pd.concat(chunks)
    return combined[~combined.index.duplicated(keep="first")].sort_index()


def fmt(m: dict) -> str:
    return (
        f"cagr={m['cagr_pct']:.1f}% maxdd={m['max_drawdown_pct']:.1f}% "
        f"sharpe={m['sharpe_ratio']:.2f} win_rate={m['win_rate_pct']:.1f}% trades={m['num_trades']}"
    )


def calmar(m: dict) -> float:
    dd = abs(m["max_drawdown_pct"])
    return m["cagr_pct"] / dd if dd > 0 else float("-inf")


def run_backtest(strategy_kwargs: dict, bars: dict) -> dict:
    strategy = EmaCrossoverStrategy(**strategy_kwargs)
    engine = CfdBacktestEngine(
        strategy=strategy,
        starting_equity=10_000.0,
        risk_per_trade=settings.cfd_risk_per_trade,
        max_open_positions=settings.cfd_max_open_positions,
        max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
    )
    return engine.run(bars)["metrics"]


def split(bars: dict[str, pd.DataFrame]) -> tuple[dict, dict]:
    train, test = {}, {}
    for sym, df in bars.items():
        cut = int(len(df) * TRAIN_FRACTION)
        train[sym] = df.iloc[:cut]
        test[sym] = df.iloc[cut:]
    return train, test


async def main():
    broker = DerivBroker()
    try:
        await broker.connect()
        bars = {}
        for instrument in settings.cfd_instruments:
            print(f"Fetching {instrument} history ({GRANULARITY_SECONDS}s bars, up to {CHUNKS_PER_INSTRUMENT} chunks)...")
            df = await fetch_history(broker, instrument)
            span = f"{df.index[0]} to {df.index[-1]}" if not df.empty else "no data"
            print(f"  {len(df)} bars, {span}")
            bars[instrument] = df
    finally:
        await broker.close()

    bars = {sym: df for sym, df in bars.items() if not df.empty}
    if not bars:
        print("No history fetched for any instrument -- aborting.")
        return

    train_bars, test_bars = split(bars)
    train_start = min(df.index[0] for df in train_bars.values() if not df.empty)
    train_end = max(df.index[-1] for df in train_bars.values() if not df.empty)
    print(f"\nTRAIN: {train_start} to {train_end} ({TRAIN_FRACTION:.0%} of fetched bars per instrument)")

    baseline_train = run_backtest({}, train_bars)
    baseline_test = run_backtest({}, test_bars)
    print("\nBaseline (default EmaCrossoverStrategy params):")
    print(f"  TRAIN {fmt(baseline_train)}")
    print(f"  TEST  {fmt(baseline_test)}")

    keys = list(PARAM_GRID.keys())
    combos = [
        dict(zip(keys, values)) for values in itertools.product(*PARAM_GRID.values()) if values[0] < values[1]
    ]  # fast_span < slow_span, or the "crossover" is meaningless
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
        f"\nTop 5 by TRAIN calmar (cagr/|maxdd|) among combos with CAGR > 0 "
        f"and drawdown no worse than {MAX_DRAWDOWN_CAP}% ({len(pool)}/{len(results)} qualify):"
    )
    for kwargs, m in pool[:5]:
        print(f"  calmar={calmar(m):.2f}  {kwargs} -> {fmt(m)}")

    if not pool:
        print(f"\nNo combination qualified (min {MIN_TRADES} trades, CAGR>0, drawdown cap). Keeping current defaults.")
        return

    best_kwargs, best_train = pool[0]
    best_test = run_backtest(best_kwargs, test_bars)

    print(f"\n=== Best candidate: {best_kwargs} ===")
    print(f"  TRAIN {fmt(best_train)}")
    print(f"  TEST  {fmt(best_test)}")

    overfit = best_test["cagr_pct"] <= 0 or best_test["max_drawdown_pct"] < MAX_DRAWDOWN_CAP
    if overfit:
        print("\n  WARNING: does not hold up out-of-sample -- likely overfit to TRAIN. NOT recommended as-is.")
    else:
        print("\n  Holds up out-of-sample -- recommended.")


if __name__ == "__main__":
    asyncio.run(main())

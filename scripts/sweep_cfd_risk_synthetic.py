"""Same risk_per_trade sweep as sweep_cfd_risk.py, but on Deriv's
Synthetic Indices (Volatility 10/25/50/75/100) instead of forex/gold --
an avenue not tried yet. These trade 24/7 with no real-world news/
liquidity dependence (pure algorithmically-generated price series), so
their statistical behavior could plausibly be more persistent than a
real market's -- or could just be a different flavor of the same "edge
too thin to leverage" problem already found on forex/gold and crypto.
Measuring, not assuming, either way.

No yfinance equivalent exists for these (they're Deriv's own product,
not traded anywhere else) -- always fetched from Deriv itself. Deriv's
per-granularity history-depth limits (documented in
optimize_cfd_strategy.py for forex/gold) haven't been checked for
synthetic indices specifically; this script prints how much history it
actually got so that can be judged directly.

Needs a live network connection -- run via the "CFD Manual Command"
GitHub Actions workflow and read its job logs.

Usage: python scripts/sweep_cfd_risk_synthetic.py [--granularity 3600]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.broker import DerivBroker
from trading.cfd.strategy import EmaCrossoverStrategy
from trading.config import settings

from optimize_cfd_strategy import CHUNKS_PER_INSTRUMENT, TRAIN_FRACTION, fetch_history, fmt, split
from sweep_cfd_risk import RISK_PER_TRADE_GRID, survival_after_losses

SYNTHETIC_INSTRUMENTS = ["R_10", "R_25", "R_50", "R_75", "R_100"]


def run_backtest(risk_per_trade: float, bars: dict) -> dict:
    strategy = EmaCrossoverStrategy()  # same validated (forex/gold) defaults -- not re-tuned for synthetics
    engine = CfdBacktestEngine(
        strategy=strategy,
        starting_equity=10_000.0,
        risk_per_trade=risk_per_trade,
        max_open_positions=settings.cfd_max_open_positions,
        max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
        spread_pct=settings.cfd_backtest_spread_pct,
        daily_financing_pct=settings.cfd_backtest_daily_financing_pct,
    )
    return engine.run(bars)["metrics"]


async def main(granularity_seconds: int):
    bars = {}
    broker = DerivBroker()
    try:
        await broker.connect()
        for instrument in SYNTHETIC_INSTRUMENTS:
            print(f"Fetching {instrument} history ({granularity_seconds}s bars, up to {CHUNKS_PER_INSTRUMENT} chunks)...")
            df = await fetch_history(broker, instrument, granularity_seconds)
            span = f"{df.index[0]} to {df.index[-1]}" if not df.empty else "no data"
            print(f"  total: {len(df)} bars, {span}")
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
    test_start = min(df.index[0] for df in test_bars.values() if not df.empty)
    test_end = max(df.index[-1] for df in test_bars.values() if not df.empty)
    print(f"\nTRAIN: {train_start} to {train_end} ({TRAIN_FRACTION:.0%} of fetched bars per instrument)")
    print(f"TEST:  {test_start} to {test_end}")

    print(f"\n{'risk/trade':>10} | {'TRAIN':<62} | {'TEST':<62} | survival after 5/10 full-stop losses in a row")
    print("-" * 170)
    for r in RISK_PER_TRADE_GRID:
        train_m = run_backtest(r, train_bars)
        test_m = run_backtest(r, test_bars)
        surv5 = survival_after_losses(r, 5)
        surv10 = survival_after_losses(r, 10)
        print(f"{r:>10.0%} | {fmt(train_m):<62} | {fmt(test_m):<62} | {surv5:.1f}% / {surv10:.1f}% of equity left")

    print(
        "\nLooking for: a risk level where BOTH TRAIN and TEST cagr support "
        "months-scale doubling (roughly 290%+/year) AND maxdd stays well "
        "short of account-destroying (say, better than -70%) on BOTH "
        "periods -- not just one. A row meeting that on only one of "
        "TRAIN/TEST is not a finding, it's noise; report both regardless."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    args = parser.parse_args()
    asyncio.run(main(args.granularity))

"""Sweeps CfdRiskManager's risk_per_trade at DonchianBreakoutStrategy's
newly-validated params (entry_window=80, exit_window=15,
atr_stop_mult=3.5, atr_target_mult=6.0 -- the one candidate that held
up on BOTH TRAIN and TEST out of optimize_cfd_breakout.py's grid
search: TRAIN cagr=7.9% maxdd=-22.4%, TEST cagr=9.8% maxdd=-17.6%,
consistent in sign and magnitude, unlike every EmaCrossoverStrategy
risk sweep tried before this).

Same purpose and discipline as sweep_cfd_risk.py (see that script's
docstring): measure what raising risk_per_trade actually does to this
specific edge rather than assume it behaves like the EMA crossover's
did. A more consistent, positive-on-both-periods edge is exactly the
condition under which Kelly-criterion reasoning says more risk COULD
be tolerated -- but that's a hypothesis to check against real numbers,
not something to act on by assumption, the same discipline applied
everywhere else in this project.

Needs a live network connection -- run via the "CFD Manual Command"
GitHub Actions workflow and read its job logs.

Usage: python scripts/sweep_cfd_risk_breakout.py [--granularity 3600] [--source deriv|yfinance]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.breakout import DonchianBreakoutStrategy
from trading.cfd.broker import DerivBroker
from trading.config import settings

from optimize_cfd_strategy import TRAIN_FRACTION, fetch_history, fetch_history_yfinance, fmt, split, YFINANCE_INTERVAL_BY_GRANULARITY
from sweep_cfd_risk import RISK_PER_TRADE_GRID, survival_after_losses

# The one robust candidate from optimize_cfd_breakout.py's search.
BEST_PARAMS = {"entry_window": 80, "exit_window": 15, "atr_stop_mult": 3.5, "atr_target_mult": 6.0}


def run_backtest(risk_per_trade: float, bars: dict) -> dict:
    strategy = DonchianBreakoutStrategy(**BEST_PARAMS)
    engine = CfdBacktestEngine(
        strategy=strategy,
        starting_equity=10_000.0,
        risk_per_trade=risk_per_trade,
        max_open_positions=settings.cfd_max_open_positions,
        max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
    )
    return engine.run(bars)["metrics"]


async def main(granularity_seconds: int, source: str):
    bars = {}
    if source == "deriv":
        broker = DerivBroker()
        try:
            await broker.connect()
            for instrument in settings.cfd_instruments:
                print(f"Fetching {instrument} history ({granularity_seconds}s bars)...")
                df = await fetch_history(broker, instrument, granularity_seconds)
                bars[instrument] = df
        finally:
            await broker.close()
    else:
        interval = YFINANCE_INTERVAL_BY_GRANULARITY.get(granularity_seconds, "1h")
        print(f"Fetching from yfinance (interval={interval})...")
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
    print(f"Fixed strategy params: {BEST_PARAMS}")

    print(f"\n{'risk/trade':>10} | {'TRAIN':<62} | {'TEST':<62} | survival after 5/10 full-stop losses in a row")
    print("-" * 170)
    for r in RISK_PER_TRADE_GRID:
        train_m = run_backtest(r, train_bars)
        test_m = run_backtest(r, test_bars)
        surv5 = survival_after_losses(r, 5)
        surv10 = survival_after_losses(r, 10)
        print(f"{r:>10.0%} | {fmt(train_m):<62} | {fmt(test_m):<62} | {surv5:.1f}% / {surv10:.1f}% of equity left")

    print(
        "\nLooking for: a risk level where BOTH TRAIN and TEST cagr climb toward "
        "months-scale doubling (roughly 290%+/year) while maxdd stays survivable "
        "on BOTH periods -- not a row that's only good on one. Report both "
        "regardless of what's found."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    parser.add_argument("--source", choices=["deriv", "yfinance"], default="yfinance")
    args = parser.parse_args()
    asyncio.run(main(args.granularity, args.source))

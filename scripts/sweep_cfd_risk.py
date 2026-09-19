"""Sweeps CfdRiskManager's risk_per_trade at the already-validated
EmaCrossoverStrategy defaults (fast_span=15, slow_span=34,
atr_stop_mult=2.0, atr_target_mult=2.0 -- see strategy.py's docstring),
to show concretely what happens to returns AND drawdown as risk per
trade increases, instead of guessing a number.

Context: the validated strategy's own TRAIN/TEST CAGR (~3-5%/year)
implies a ~15-21 year doubling time at the current
CFD_RISK_PER_TRADE=0.01. Reaching a months-scale doubling target would
need a CAGR of roughly 290-1500%+/year depending on how many months --
this script doesn't try to hit that number by picking a big
risk_per_trade; it measures what actually happens on real history at a
range of values (both TRAIN and TEST, same overfit-safety split as
optimize_cfd_strategy.py) so the tradeoff (growth rate vs. proximity to
a capital-floor/ruin-level drawdown) is visible before any live change.

Same TRAIN/TEST discipline and data sources as optimize_cfd_strategy.py
(--source deriv|yfinance) -- see that script's docstring for why H1/
yfinance data is used rather than Deriv's own M15 history (too short to
trust). Strategy parameters are held fixed at the validated defaults;
only risk_per_trade varies.

Needs a live network connection (this sandbox has no general internet
access) -- run via the "CFD Manual Command" GitHub Actions workflow and
read its job logs.

Usage: python scripts/sweep_cfd_risk.py [--granularity 3600] [--source deriv|yfinance]
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

from optimize_cfd_strategy import (
    CHUNKS_PER_INSTRUMENT,
    TRAIN_FRACTION,
    fetch_history,
    fetch_history_yfinance,
    fmt,
    split,
    YFINANCE_INTERVAL_BY_GRANULARITY,
)

# Wide net on purpose: the point is to find where it breaks, not to
# assume it's safe somewhere in a narrow "reasonable" band.
RISK_PER_TRADE_GRID = [0.01, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]

# A run of N consecutive full-stop losses at risk fraction r leaves
# (1-r)^N of starting equity -- printed alongside each row so "max
# drawdown in this particular backtest window" isn't mistaken for "the
# worst that can ever happen." 5 and 10 losses in a row is not exotic
# for a ~48% win-rate strategy.
def survival_after_losses(risk_per_trade: float, n: int) -> float:
    return (1 - risk_per_trade) ** n * 100


def run_backtest(risk_per_trade: float, bars: dict) -> dict:
    strategy = EmaCrossoverStrategy()  # fixed at validated defaults
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

    print(
        f"\n{'risk/trade':>10} | {'TRAIN':<62} | {'TEST':<62} | survival after 5/10 full-stop losses in a row"
    )
    print("-" * 170)
    for r in RISK_PER_TRADE_GRID:
        train_m = run_backtest(r, train_bars)
        test_m = run_backtest(r, test_bars)
        surv5 = survival_after_losses(r, 5)
        surv10 = survival_after_losses(r, 10)
        print(
            f"{r:>10.0%} | {fmt(train_m):<62} | {fmt(test_m):<62} | "
            f"{surv5:.1f}% / {surv10:.1f}% of equity left"
        )

    print(
        "\nReading this table: cagr/maxdd both climb together as risk/trade "
        "rises -- there is no free lunch here, higher risk did not just buy "
        "higher return, it bought proportionally worse drawdown too. The "
        "'survival after N losses' columns are the blunt version of the "
        "same point: at high risk/trade, a perfectly ordinary losing streak "
        "for a ~48%% win-rate strategy (5-10 losses in a row happens by "
        "chance far more often than intuition suggests) leaves very little "
        "of the account left, even though this backtest's own max drawdown "
        "may look survivable -- max drawdown in ONE historical window is "
        "not a guarantee about the next one. There is no 'safe high-risk' "
        "row in this table; every row is a tradeoff, chosen by the user, "
        "not a recommendation from this script."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    parser.add_argument("--source", choices=["deriv", "yfinance"], default="yfinance")
    args = parser.parse_args()
    asyncio.run(main(args.granularity, args.source))

"""Grid-search EmaCrossoverStrategy's parameters against real Deriv
history, validated out-of-sample -- the CFD/forex counterpart of
scripts/optimize_strategy.py, same discipline: history splits into a
TRAIN period (the grid search runs here) and a TEST/holdout period
touched only once at the end, as a sanity check against curve-fitting.
Any combo whose TRAIN max drawdown breaches MAX_DRAWDOWN_CAP is rejected
outright, however good its return -- "the portfolio must not blow up"
stays a hard constraint, not something the search can trade away for a
better number. The winning candidate also has to beat the untouched
default params' own TEST performance, not just clear CAGR>0 and the
drawdown cap in isolation -- a candidate that passes that bar in
isolation but does worse than doing nothing on real holdout data is
not an improvement, whatever its TRAIN numbers looked like (found this
the hard way on the first real run: a "recommended" candidate scored
72% TRAIN CAGR but only 1.8% TEST CAGR, well under the default params'
31% TEST CAGR).

Backtests all configured instruments together, sharing one
CfdRiskManager -- matching how the live scheduler actually trades them
(shared max_open_positions, shared daily-loss circuit breaker), not as
independent single-instrument backtests.

Two history sources:
  --source deriv (default): the real feed the bot trades on, but Deriv
    caps M15 candle depth at ~3 months regardless of pagination (a
    server-side limit, confirmed by the identical pagination code
    reaching ~11 months at H1 granularity) -- too short to trust a
    train/test split on at M15.
  --source yfinance: Yahoo Finance, already a trusted dependency in this
    project (used for the stock system's earnings dates) -- gives up to
    ~2 years of hourly forex/gold history, a credible longer-window
    cross-check when Deriv's own window is too short. It's a proxy, not
    Deriv's exact feed (different vendor, e.g. COMEX gold futures GC=F
    standing in for spot XAUUSD) -- informative for validating the
    EMA-crossover approach directionally, not a substitute for
    eventually backtesting the live bot's own accumulated M15 history.

Needs a live network connection (this sandbox has no general internet
access) -- run via the "CFD Manual Command" GitHub Actions workflow
(command=optimize-strategy) and read its job logs.

Usage: python scripts/optimize_cfd_strategy.py [--granularity 900] [--source deriv|yfinance]
"""
import argparse
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

CHUNK_COUNT = 5000  # Deriv's approx per-request cap for ticks_history
CHUNKS_PER_INSTRUMENT = 8  # up to 8 requests per instrument, paged backward

TRAIN_FRACTION = 0.7  # proportional, not fixed calendar dates -- history depth isn't known ahead of a live fetch
MIN_TRADES = 20  # ignore combos too thin to trust their metrics
MAX_DRAWDOWN_CAP = -25.0  # reject any combo whose TRAIN max drawdown is worse than this

PARAM_GRID = {
    "fast_span": [8, 12, 16],
    "slow_span": [21, 26, 34],
    "atr_stop_mult": [1.0, 1.5, 2.0],
    "atr_target_mult": [1.5, 2.5, 3.5],
}

# Yahoo Finance ticker candidates per Deriv instrument, tried in order --
# not the same vendor/feed as Deriv, so treat as a directional proxy.
YFINANCE_TICKERS = {
    "frxEURUSD": ["EURUSD=X"],
    "frxGBPUSD": ["GBPUSD=X"],
    "frxUSDJPY": ["USDJPY=X", "JPY=X"],
    "frxXAUUSD": ["XAUUSD=X", "GC=F"],
}
YFINANCE_INTERVAL_BY_GRANULARITY = {900: "15m", 3600: "1h", 86400: "1d"}
YFINANCE_PERIOD_BY_INTERVAL = {"15m": "60d", "1h": "730d", "1d": "10y"}


def fetch_history_yfinance(instrument: str, interval: str) -> pd.DataFrame:
    import yfinance as yf

    period = YFINANCE_PERIOD_BY_INTERVAL.get(interval, "730d")
    candidates = YFINANCE_TICKERS.get(instrument, [])
    if not candidates:
        print(f"  no known yfinance ticker mapping for {instrument} -- skipping")
        return pd.DataFrame(columns=["open", "high", "low", "close"])

    for ticker in candidates:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if df is None or df.empty:
            print(f"  yfinance ticker {ticker}: no data, trying next candidate...")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [str(c[0]).lower() for c in df.columns]
        else:
            df.columns = [str(c).lower() for c in df.columns]
        out = df[["open", "high", "low", "close"]].copy()
        out.index = pd.to_datetime(out.index, utc=True)
        out.index.name = "time"
        print(f"  {instrument} -> yfinance {ticker}: {len(out)} bars, {out.index[0]} to {out.index[-1]}")
        return out
    print(f"  no yfinance data found for {instrument} under any candidate ticker ({candidates})")
    return pd.DataFrame(columns=["open", "high", "low", "close"])


async def fetch_history(broker: DerivBroker, symbol: str, granularity_seconds: int) -> pd.DataFrame:
    chunks = []
    end: str | int = "latest"
    for i in range(CHUNKS_PER_INSTRUMENT):
        bars = await broker.get_candles(symbol, granularity_seconds=granularity_seconds, count=CHUNK_COUNT, end=end)
        if bars.empty:
            print(f"    chunk {i}: empty response, stopping")
            break
        print(f"    chunk {i}: {len(bars)} bars, {bars.index[0]} to {bars.index[-1]} (requested end={end})")
        chunks.append(bars)
        oldest_epoch = int(bars.index[0].timestamp())
        next_end = oldest_epoch - granularity_seconds
        if next_end == end:  # no progress -- hit the start of available history
            print("    no progress from last chunk -- stopping")
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
        print(f"Fetching from yfinance (interval={interval}, a proxy feed -- see module docstring)...")
        for instrument in settings.cfd_instruments:
            bars[instrument] = fetch_history_yfinance(instrument, interval)

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
    underperforms_baseline = best_test["cagr_pct"] < baseline_test["cagr_pct"]
    if overfit:
        print("\n  WARNING: does not hold up out-of-sample -- likely overfit to TRAIN. NOT recommended as-is.")
    elif underperforms_baseline:
        print(
            f"\n  Clears the drawdown/CAGR>0 gate, but underperforms the untouched default params on "
            f"TEST ({best_test['cagr_pct']:.1f}% vs baseline's {baseline_test['cagr_pct']:.1f}%). "
            "NOT recommended -- keep the current defaults instead."
        )
    else:
        print("\n  Holds up out-of-sample and beats the default params on TEST -- recommended.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--granularity",
        type=int,
        default=900,
        help="Candle size in seconds (Deriv-supported: 60,120,180,300,600,900,1800,3600,7200,14400,86400). "
        "Coarser granularities may have longer history available -- use e.g. 3600 to check.",
    )
    parser.add_argument(
        "--source",
        choices=["deriv", "yfinance"],
        default="deriv",
        help="deriv: the real feed the bot trades on, capped at ~3 months for M15. "
        "yfinance: Yahoo Finance proxy feed, longer history available -- see module docstring.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.granularity, args.source))

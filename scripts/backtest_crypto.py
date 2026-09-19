"""Checks whether EmaCrossoverStrategy's already-validated (forex/gold)
parameters hold up at all on crypto -- a different, generally more
volatile instrument class -- before ever considering adding
cryBTCUSD/cryETHUSD to live CFD_INSTRUMENTS. Deliberately NOT a full
grid search (see optimize_cfd_strategy.py for that): this just measures
the existing validated defaults on crypto's own price history first, on
the same discipline used throughout this project of measuring before
optimizing -- a full parameter search is only worth running if the
defaults show promise here, not as a first move.

Same TRAIN/TEST split discipline as optimize_cfd_strategy.py. Uses
yfinance (BTC-USD, ETH-USD) rather than Deriv's own history -- Deriv's
crypto candle history depth hasn't been checked yet, and yfinance is
already a trusted, credible dependency here (see optimize_cfd_strategy.py's
docstring for why forex/gold uses it as a longer-history cross-check).

Needs a live network connection (this sandbox has no general internet
access) -- run via the "CFD Manual Command" GitHub Actions workflow or
similar, and read its job logs.

Usage: python scripts/backtest_crypto.py [--granularity 3600]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.strategy import EmaCrossoverStrategy
from trading.config import settings

TRAIN_FRACTION = 0.7

CRYPTO_YFINANCE_TICKERS = {
    "cryBTCUSD": "BTC-USD",
    "cryETHUSD": "ETH-USD",
}
YFINANCE_INTERVAL_BY_GRANULARITY = {900: "15m", 3600: "1h", 86400: "1d"}
YFINANCE_PERIOD_BY_INTERVAL = {"15m": "60d", "1h": "730d", "1d": "10y"}


def fetch_history_yfinance(ticker: str, interval: str) -> pd.DataFrame:
    import yfinance as yf

    period = YFINANCE_PERIOD_BY_INTERVAL.get(interval, "730d")
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if df is None or df.empty:
        print(f"  {ticker}: no data")
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    out = df[["open", "high", "low", "close"]].copy()
    out.index = pd.to_datetime(out.index, utc=True)
    out.index.name = "time"
    print(f"  {ticker}: {len(out)} bars, {out.index[0]} to {out.index[-1]}")
    return out


def fmt(m: dict) -> str:
    return (
        f"cagr={m['cagr_pct']:.1f}% maxdd={m['max_drawdown_pct']:.1f}% "
        f"sharpe={m['sharpe_ratio']:.2f} win_rate={m['win_rate_pct']:.1f}% trades={m['num_trades']}"
    )


def run_backtest(bars: dict) -> dict:
    strategy = EmaCrossoverStrategy()  # validated forex/gold defaults, unchanged
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


def main(granularity_seconds: int):
    interval = YFINANCE_INTERVAL_BY_GRANULARITY.get(granularity_seconds, "1h")
    print(f"Fetching crypto history from yfinance (interval={interval})...")
    bars = {}
    for symbol, ticker in CRYPTO_YFINANCE_TICKERS.items():
        bars[symbol] = fetch_history_yfinance(ticker, interval)
    bars = {sym: df for sym, df in bars.items() if not df.empty}
    if not bars:
        print("No history fetched -- aborting.")
        return

    train_bars, test_bars = split(bars)
    train_start = min(df.index[0] for df in train_bars.values() if not df.empty)
    train_end = max(df.index[-1] for df in train_bars.values() if not df.empty)
    print(f"\nTRAIN: {train_start} to {train_end} ({TRAIN_FRACTION:.0%} of fetched bars per symbol)")

    print("\nEmaCrossoverStrategy at its forex/gold-validated defaults, run on crypto (all symbols together, shared risk pool):")
    train_m = run_backtest(train_bars)
    test_m = run_backtest(test_bars)
    print(f"  TRAIN {fmt(train_m)}")
    print(f"  TEST  {fmt(test_m)}")

    print("\nEach symbol alone, for comparison (isolates whether one symbol is carrying/dragging the combined result):")
    for symbol in bars:
        m_train = run_backtest({symbol: train_bars[symbol]})
        m_test = run_backtest({symbol: test_bars[symbol]})
        print(f"  {symbol}")
        print(f"    TRAIN {fmt(m_train)}")
        print(f"    TEST  {fmt(m_test)}")

    print(
        "\nReading this: if TEST here looks comparable to or better than the forex/gold "
        "baseline (TRAIN cagr=3.4%, TEST cagr=4.8%, see README), a full grid search "
        "(mirroring optimize_cfd_strategy.py) is worth running for crypto specifically. "
        "If it's clearly worse or wildly inconsistent between TRAIN/TEST, that's a real "
        "finding too -- crypto's volatility profile may simply not suit this strategy's "
        "parameters, and forcing a fit would risk the same overfitting this project has "
        "deliberately guarded against elsewhere. Either way, NOT a recommendation to add "
        "these to CFD_INSTRUMENTS by itself -- that decision needs this result reported "
        "and reasoned about, not applied automatically."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    args = parser.parse_args()
    main(args.granularity)

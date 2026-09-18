"""One-off analysis: does focusing on GLD (gold) beat the current diversified
watchlist, using the same Breakout strategy and risk settings for both?

Not a permanent script -- ad hoc comparison requested in chat.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from trading.backtest.engine import BacktestEngine
from trading.backtest.metrics import compute_metrics
from trading.config import settings
from trading.data.market_data import load_watchlist_bars
from trading.strategy.breakout import BreakoutStrategy

FETCH_START = "2019-01-01"

PORTFOLIOS = {
    "Current (diversified, all 7)": ["SPY", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "GLD"],
    "Gold-focused (GLD only)": ["GLD"],
    "Stocks-only (no GLD, for contrast)": ["SPY", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
}

PERIODS = [
    ("2020-2021 (COVID crash + recovery)", "2020-01-01", "2021-12-31"),
    ("2022 (rate-hike bear market)", "2022-01-01", "2022-12-31"),
    ("2023-2024 (recovery/bull)", "2023-01-01", "2024-12-31"),
    ("2025-present (recent)", "2025-01-01", None),
    ("Full span (2020-present)", "2020-01-01", None),
]


def slice_metrics(equity_curve, trades, start, end):
    sliced = equity_curve.loc[start:end] if end else equity_curve.loc[start:]
    if sliced.empty:
        return compute_metrics(sliced, [])
    start_ts, end_ts = sliced.index[0], sliced.index[-1]
    sliced_trades = [t for t in trades if start_ts <= t["entry_date"] <= end_ts]
    return compute_metrics(sliced, sliced_trades)


def main():
    all_symbols = sorted(set(sym for syms in PORTFOLIOS.values() for sym in syms))
    print(f"Fetching bars for {all_symbols} ...")
    all_bars = load_watchlist_bars(all_symbols, start=FETCH_START)

    results = {}
    for name, symbols in PORTFOLIOS.items():
        bars = {s: all_bars[s] for s in symbols}
        engine = BacktestEngine(
            strategy=BreakoutStrategy(),
            starting_equity=100_000.0,
            risk_per_trade=settings.risk_per_trade,
            max_open_positions=settings.max_open_positions,
            max_daily_loss_pct=settings.max_daily_loss_pct,
        )
        result = engine.run(bars)
        results[name] = result

    for label, start, end in PERIODS:
        print(f"\n=== {label} ===")
        header = f"{'Portfolio':<38}{'Return%':>10}{'CAGR%':>10}{'Sharpe':>9}{'MaxDD%':>9}{'Trades':>8}{'Win%':>8}"
        print(header)
        for name, result in results.items():
            m = slice_metrics(result["equity_curve"], result["trades"], start, end)
            print(
                f"{name:<38}{m['total_return_pct']:>10}{m['cagr_pct']:>10}"
                f"{m['sharpe_ratio']:>9}{m['max_drawdown_pct']:>9}{m['num_trades']:>8}{m['win_rate_pct']:>8}"
            )


if __name__ == "__main__":
    main()

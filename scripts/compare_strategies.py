"""Compare all strategies against each other across several historical
market regimes (bull, bear, recovery, recent) to see which one held up best
when.

Fetches price history once (with a buffer before the earliest period for
indicator warmup), backtests each strategy over the whole span, then slices
each strategy's resulting equity curve and trade log by period -- so a
period's numbers reflect only what happened during it, without re-running
the backtest (and re-doing warmup) per period.

Usage: python scripts/compare_strategies.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from trading.backtest.engine import BacktestEngine
from trading.backtest.metrics import compute_metrics
from trading.config import settings
from trading.data.market_data import load_daily_bars_yfinance, load_watchlist_bars
from trading.strategy.breakout import BreakoutStrategy
from trading.strategy.buy_and_hold import BuyAndHoldStrategy
from trading.strategy.macd_trend import MacdTrendStrategy
from trading.strategy.mean_reversion import MeanReversionStrategy
from trading.strategy.regime_adaptive import RegimeAdaptiveStrategy
from trading.strategy.trend_momentum import TrendMomentumStrategy

# (label, start, end) -- end=None means "through the most recent bar"
PERIODS = [
    ("2020-2021 (COVID crash + recovery)", "2020-01-01", "2021-12-31"),
    ("2022 (rate-hike bear market)", "2022-01-01", "2022-12-31"),
    ("2023-2024 (recovery/bull)", "2023-01-01", "2024-12-31"),
    ("2025-present (recent)", "2025-01-01", None),
    ("Full span (2020-present)", "2020-01-01", None),
]

FETCH_START = "2019-01-01"  # buffer before the earliest period, for indicator warmup


def slice_metrics(equity_curve: pd.Series, trades: list[dict], start: str, end: str | None) -> dict:
    sliced_curve = equity_curve.loc[start:end] if end else equity_curve.loc[start:]
    if sliced_curve.empty:
        return compute_metrics(sliced_curve, [])
    start_ts, end_ts = sliced_curve.index[0], sliced_curve.index[-1]
    sliced_trades = [t for t in trades if start_ts <= t["entry_date"] <= end_ts]
    return compute_metrics(sliced_curve, sliced_trades)


def main():
    symbols = settings.watchlist
    print(f"Fetching {symbols} from {FETCH_START} (regime reference: {settings.regime_symbol}) ...\n")
    bars = load_watchlist_bars(symbols, start=FETCH_START)
    regime_bars = load_daily_bars_yfinance(settings.regime_symbol, start=FETCH_START)

    strategies = {
        "trend_momentum": TrendMomentumStrategy(),
        "mean_reversion": MeanReversionStrategy(),
        "macd_trend": MacdTrendStrategy(),
        "breakout": BreakoutStrategy(),
        "buy_and_hold": BuyAndHoldStrategy(),
        "regime_adaptive": RegimeAdaptiveStrategy(regime_bars=regime_bars),
    }

    results = {}
    for name, strategy in strategies.items():
        engine = BacktestEngine(
            strategy=strategy,
            starting_equity=100_000.0,
            risk_per_trade=settings.risk_per_trade,
            max_open_positions=settings.max_open_positions,
            max_daily_loss_pct=settings.max_daily_loss_pct,
        )
        results[name] = engine.run(bars)

    for label, start, end in PERIODS:
        print(f"=== {label} ===")
        rows = [(name, slice_metrics(run["equity_curve"], run["trades"], start, end)) for name, run in results.items()]
        rows.sort(key=lambda r: r[1]["cagr_pct"], reverse=True)

        print(f"{'strategy':<18}{'cagr%':>8}{'sharpe':>9}{'maxdd%':>9}{'winrate%':>10}{'trades':>8}")
        for name, m in rows:
            print(
                f"{name:<18}{m['cagr_pct']:>8.1f}{m['sharpe_ratio']:>9.2f}"
                f"{m['max_drawdown_pct']:>9.1f}{m['win_rate_pct']:>10.1f}{m['num_trades']:>8}"
            )
        print(f"Best this period: {rows[0][0]}\n")


if __name__ == "__main__":
    main()

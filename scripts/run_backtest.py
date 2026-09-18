"""Backtest the default trend+momentum strategy over the configured watchlist.

Usage: python scripts/run_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.backtest.engine import BacktestEngine
from trading.config import settings
from trading.data.market_data import load_watchlist_bars
from trading.strategy.trend_momentum import TrendMomentumStrategy


def main():
    symbols = settings.watchlist
    print(f"Backtesting {symbols} ...")
    bars = load_watchlist_bars(symbols, start="2020-01-01")

    engine = BacktestEngine(
        strategy=TrendMomentumStrategy(),
        starting_equity=100_000.0,
        risk_per_trade=settings.risk_per_trade,
        max_open_positions=settings.max_open_positions,
        max_daily_loss_pct=settings.max_daily_loss_pct,
    )
    result = engine.run(bars)

    print("\n=== Metrics ===")
    for key, value in result["metrics"].items():
        print(f"{key}: {value}")

    print(f"\n{len(result['trades'])} trades executed.")


if __name__ == "__main__":
    main()

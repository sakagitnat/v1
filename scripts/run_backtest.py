"""Backtest the strategy over the configured watchlist.

Uses Breakout by default: in a full comparison across 2020-present, it beat
regime_adaptive (and every other strategy except the far-riskier buy-and-hold)
on CAGR, Sharpe, and max drawdown all at once -- the added complexity of
switching strategies by market regime wasn't earning its keep once Breakout
itself was tuned for profit-per-drawdown-risk (see optimize_strategy.py
--objective calmar). Swap `strategy=` below to backtest a different one.

Usage: python scripts/run_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.backtest.engine import BacktestEngine
from trading.config import settings
from trading.data.market_data import load_watchlist_bars
from trading.strategy.breakout import BreakoutStrategy

FETCH_START = "2019-01-01"  # buffer before 2020 so indicators are already warm


def main():
    symbols = settings.watchlist
    print(f"Backtesting {symbols} ...")
    bars = load_watchlist_bars(symbols, start=FETCH_START)

    engine = BacktestEngine(
        strategy=BreakoutStrategy(),
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

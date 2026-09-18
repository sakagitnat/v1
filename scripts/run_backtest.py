"""Backtest the strategy over the configured watchlist.

Uses the regime-adaptive strategy by default: it switches between Breakout,
Mean Reversion, and MACD Trend sub-strategies based on the broad market's
trend (see src/trading/strategy/regime_adaptive.py). Swap `strategy=` below
to backtest a single strategy instead.

Usage: python scripts/run_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.backtest.engine import BacktestEngine
from trading.config import settings
from trading.data.market_data import load_daily_bars_yfinance, load_watchlist_bars
from trading.strategy.regime_adaptive import RegimeAdaptiveStrategy

FETCH_START = "2019-01-01"  # buffer before 2020 so 200-day indicators are already warm


def main():
    symbols = settings.watchlist
    print(f"Backtesting {symbols} (regime reference: {settings.regime_symbol}) ...")
    bars = load_watchlist_bars(symbols, start=FETCH_START)
    regime_bars = load_daily_bars_yfinance(settings.regime_symbol, start=FETCH_START)

    engine = BacktestEngine(
        strategy=RegimeAdaptiveStrategy(regime_bars=regime_bars),
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

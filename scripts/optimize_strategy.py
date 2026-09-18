"""Grid-search a strategy's parameters to raise win rate WITHOUT sacrificing
profitability, validated out-of-sample so a result that only looks good
because it's curve-fit to history gets caught instead of shipped.

History is split into a TRAIN period (the grid search runs here) and a
TEST/holdout period (never touched during the search -- the winning
parameters are evaluated on it once, at the end, as a sanity check). A
parameter set that wins on TRAIN but falls apart on TEST is overfit and is
flagged as such, not silently recommended.

Usage: python scripts/optimize_strategy.py --strategy breakout
       python scripts/optimize_strategy.py --strategy mean_reversion
       python scripts/optimize_strategy.py --strategy macd_trend
"""
import argparse
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.backtest.engine import BacktestEngine
from trading.config import settings
from trading.data.market_data import load_watchlist_bars
from trading.strategy.breakout import BreakoutStrategy
from trading.strategy.macd_trend import MacdTrendStrategy
from trading.strategy.mean_reversion import MeanReversionStrategy

FETCH_START = "2018-06-01"  # buffer before TRAIN_START for indicator warmup
TRAIN_START, TRAIN_END = "2019-01-01", "2023-12-31"
TEST_START, TEST_END = "2024-01-01", None  # None = through the most recent bar

MIN_TRADES = 20  # ignore combos too thin to trust their win rate

GRIDS = {
    "breakout": {
        "cls": BreakoutStrategy,
        "params": {
            "entry_window": [10, 15, 20, 30],
            "exit_window": [5, 10, 15],
            "atr_stop_mult": [1.5, 2.0, 2.5],
            "atr_target_mult": [1.5, 2.0, 3.0, 4.0],
        },
    },
    "mean_reversion": {
        "cls": MeanReversionStrategy,
        "params": {
            "bb_std": [1.5, 2.0, 2.5],
            "rsi_oversold": [20, 25, 30, 35],
            "atr_stop_mult": [1.5, 2.0, 2.5],
            "atr_target_mult": [1.5, 2.0, 3.0],
        },
    },
    "macd_trend": {
        "cls": MacdTrendStrategy,
        "params": {
            "atr_stop_mult": [1.5, 2.0, 2.5, 3.0],
            "atr_target_mult": [2.0, 3.0, 4.0, 5.0],
        },
    },
}


def run_backtest(strategy, bars: dict, start: str, end: str | None) -> dict:
    sliced = {sym: (df.loc[start:end] if end else df.loc[start:]) for sym, df in bars.items()}
    engine = BacktestEngine(
        strategy=strategy,
        starting_equity=100_000.0,
        risk_per_trade=settings.risk_per_trade,
        max_open_positions=settings.max_open_positions,
        max_daily_loss_pct=settings.max_daily_loss_pct,
    )
    return engine.run(sliced)["metrics"]


def fmt(m: dict) -> str:
    return f"win_rate={m['win_rate_pct']:.1f}% cagr={m['cagr_pct']:.1f}% sharpe={m['sharpe_ratio']:.2f} trades={m['num_trades']}"


def search(strategy_name: str):
    spec = GRIDS[strategy_name]
    cls = spec["cls"]
    param_grid = spec["params"]

    print(f"Fetching {settings.watchlist} from {FETCH_START} ...")
    bars = load_watchlist_bars(settings.watchlist, start=FETCH_START)

    baseline_train = run_backtest(cls(), bars, TRAIN_START, TRAIN_END)
    baseline_test = run_backtest(cls(), bars, TEST_START, TEST_END)
    print(f"\nBaseline ({strategy_name}, default params):")
    print(f"  TRAIN {fmt(baseline_train)}")
    print(f"  TEST  {fmt(baseline_test)}")

    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    print(f"\nSearching {len(combos)} parameter combinations on TRAIN ({TRAIN_START} to {TRAIN_END}) ...")

    results = []
    for combo in combos:
        kwargs = dict(zip(keys, combo))
        train_metrics = run_backtest(cls(**kwargs), bars, TRAIN_START, TRAIN_END)
        if train_metrics["num_trades"] < MIN_TRADES:
            continue
        results.append((kwargs, train_metrics))

    profitable = [r for r in results if r[1]["cagr_pct"] > 0]
    pool = profitable if profitable else results
    pool.sort(key=lambda r: r[1]["win_rate_pct"], reverse=True)

    print(f"\nTop 5 by TRAIN win rate ({len(profitable)}/{len(results)} combos kept CAGR > 0):")
    for kwargs, m in pool[:5]:
        print(f"  {kwargs} -> {fmt(m)}")

    if not pool:
        print("\nNo combination produced enough trades to evaluate. Try a wider grid or lower MIN_TRADES.")
        return

    best_kwargs, best_train = pool[0]
    best_test = run_backtest(cls(**best_kwargs), bars, TEST_START, TEST_END)

    print(f"\n=== Best candidate: {best_kwargs} ===")
    print(f"  TRAIN {fmt(best_train)}")
    print(f"  TEST  {fmt(best_test)}")

    overfit = best_test["cagr_pct"] <= 0 or best_test["win_rate_pct"] < baseline_test["win_rate_pct"] - 5
    if overfit:
        print("\n  WARNING: does not hold up out-of-sample -- likely overfit to TRAIN. NOT recommended as-is.")
    else:
        print("\n  Holds up out-of-sample (TEST win rate and CAGR both reasonable) -- recommended.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True, choices=list(GRIDS.keys()))
    args = parser.parse_args()
    search(args.strategy)

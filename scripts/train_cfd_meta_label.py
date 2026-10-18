"""Trains a meta-label filter (trading.cfd.meta_label /
trading.cfd.meta_labeled_strategy) over EmaCrossoverStrategy's
currently-registered, validated parameters, and compares it against
the unfiltered baseline on the same TRAIN/TEST split
optimize_cfd_strategy.py uses -- same overfitting discipline (TRAIN-
only training, TEST touched once), reusing that module's fetch/split
helpers rather than re-implementing them.

What this measures that the plain TRAIN/TEST gate can't: the meta-
model is trained to predict whether an entry EmaCrossoverStrategy would
take actually goes on to hit its target before its stop (see
trading.cfd.meta_label.triple_barrier_label), using only features
available at signal time (ADX, ATR%, EMA spread%, trend distance% --
see extract_features()'s docstring). If filtering out the low-
probability half of entries raises Sharpe/calmar on TEST without
requiring a parameter retune, that's a genuinely different lever from
anything optimize_cfd_strategy.py's grid search already explored (which
only ever varies the primary strategy's own parameters, never "should
we skip this specific signal").

Needs a live network connection -- run via the "CFD Manual Command"
GitHub Actions workflow (command=train-meta-label) and read its job
logs.

Usage: python scripts/train_cfd_meta_label.py [--granularity 3600] [--source deriv|yfinance] [--threshold 0.5]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from trading.cfd.broker import DerivBroker
from trading.cfd.deflated_sharpe import deflated_sharpe_ratio
from trading.cfd.meta_label import LogisticRegression, extract_features, triple_barrier_label
from trading.cfd.meta_labeled_strategy import MetaLabeledStrategy
from trading.cfd.strategy import EmaCrossoverStrategy
from trading.config import settings

from optimize_cfd_strategy import (
    CHUNKS_PER_INSTRUMENT,
    TRAIN_FRACTION,
    YFINANCE_INTERVAL_BY_GRANULARITY,
    _periods_per_year,
    _return_distribution_stats,
    annualized_to_per_period,
    fetch_history,
    fetch_history_yfinance,
    fmt,
    run_backtest_full,
    split,
)

MAX_HOLDING_BARS = 48  # ~2 days of H1 bars -- the vertical barrier for triple-barrier labeling
MIN_TRAINING_SAMPLES = 30  # below this, a fitted model is noise, not a filter


def collect_training_samples(strategy: EmaCrossoverStrategy, bars: dict[str, pd.DataFrame]) -> tuple[list, list]:
    """Replays `strategy` bar-by-bar, independently per instrument (no
    cross-instrument portfolio risk governor -- that's CfdBacktestEngine's
    job for an actual backtest, not relevant to "what signals would the
    primary strategy generate and how did each one turn out", which is
    all meta-label training needs). Every new entry's features and its
    eventual triple_barrier_label become one training example."""
    features: list[list[float]] = []
    labels: list[int] = []

    for symbol, df in bars.items():
        prepared = strategy.prepare(df)
        if len(prepared) < 2:
            continue

        position: dict | None = None
        for i in range(1, len(prepared)):
            row = prepared.iloc[i]
            prev_row = prepared.iloc[i - 1]
            in_position = position["side"] if position else None
            signal = strategy.signal_for_row(symbol, row, prev_row, in_position)

            if position is not None:
                hit_stop = (position["side"] == "long" and row["low"] <= position["stop"]) or (
                    position["side"] == "short" and row["high"] >= position["stop"]
                )
                hit_target = (position["side"] == "long" and row["high"] >= position["target"]) or (
                    position["side"] == "short" and row["low"] <= position["target"]
                )
                is_exit_signal = (position["side"] == "long" and signal.action.value == "sell") or (
                    position["side"] == "short" and signal.action.value == "buy"
                )
                if hit_stop or hit_target or is_exit_signal:
                    position = None
                continue

            if signal.action.value in ("buy", "sell"):
                side = "long" if signal.action.value == "buy" else "short"
                future = prepared.iloc[i + 1 :]
                label = triple_barrier_label(side, signal.price, signal.stop_price, signal.take_profit_price, future, MAX_HOLDING_BARS)
                if label is not None:
                    features.append(extract_features(row))
                    labels.append(label)
                position = {"side": side, "stop": signal.stop_price, "target": signal.take_profit_price}

    return features, labels


def report_psr(label: str, metrics: dict, equity_curve: pd.Series) -> None:
    """Single-hypothesis confidence check (no multiple-testing penalty --
    n_trials=1 -- since this script trains exactly one fixed-threshold
    model, it doesn't grid-search thresholds the way optimize_cfd_*.py
    grid-searches parameters). See deflated_sharpe.py's module docstring
    for why DSR with n_trials=1 collapses to plain PSR."""
    ppy = _periods_per_year(equity_curve)
    n_obs, skew, kurt = _return_distribution_stats(equity_curve)
    per_period_sr = annualized_to_per_period(metrics["sharpe_ratio"], ppy)
    psr = deflated_sharpe_ratio(observed_sr=per_period_sr, sr_trials_std=0.0, n_trials=1, n_obs=n_obs, skew=skew, kurtosis=kurt)
    verdict = "nan (degenerate skew/kurtosis for this SR)" if psr != psr else f"{psr:.1%}"
    print(f"  PSR ({label}, sharpe={metrics['sharpe_ratio']:.2f} annualized, n_obs={n_obs}): {verdict}")


async def main(granularity_seconds: int, source: str, threshold: float):
    bars = {}
    if source == "deriv":
        broker = DerivBroker()
        try:
            await broker.connect()
            for instrument in settings.cfd_instruments:
                print(f"Fetching {instrument} history ({granularity_seconds}s bars, up to {CHUNKS_PER_INSTRUMENT} chunks)...")
                df = await fetch_history(broker, instrument, granularity_seconds)
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
    print(f"\nTRAIN: {train_start} to {train_end} ({TRAIN_FRACTION:.0%} of fetched bars per instrument)")

    base_params = {}  # EmaCrossoverStrategy's constructor defaults ARE the currently-registered, validated params
    primary = EmaCrossoverStrategy(**base_params)

    print("\nReplaying the primary strategy over TRAIN to collect (features, triple-barrier outcome) samples...")
    features, labels = collect_training_samples(primary, train_bars)
    print(f"  {len(features)} entries, {sum(labels)} profitable ({(sum(labels) / len(labels) * 100) if labels else 0:.1f}%)")

    if len(features) < MIN_TRAINING_SAMPLES:
        print(f"\nFewer than {MIN_TRAINING_SAMPLES} training samples -- too little data to fit a meta-model. Aborting.")
        return

    model = LogisticRegression(learning_rate=0.3, l2=0.01, n_iter=1000).fit(np.array(features), np.array(labels, dtype=float))
    train_probs = model.predict_proba(np.array(features))
    print(f"  TRAIN-fit mean predicted probability: {train_probs.mean():.2f} (base rate was {np.mean(labels):.2f})")

    baseline_full = run_backtest_full(base_params, test_bars, EmaCrossoverStrategy)
    print("\nBaseline (unfiltered EmaCrossoverStrategy) on TEST:")
    print(f"  {fmt(baseline_full['metrics'])}")
    report_psr("baseline", baseline_full["metrics"], baseline_full["equity_curve"])

    meta_strategy = MetaLabeledStrategy(EmaCrossoverStrategy(**base_params), model, threshold=threshold)
    meta_full = run_backtest_full({}, test_bars, lambda **_: meta_strategy)
    print(f"\nMeta-labeled (threshold={threshold}) on TEST:")
    print(f"  {fmt(meta_full['metrics'])}")
    report_psr("meta-labeled", meta_full["metrics"], meta_full["equity_curve"])

    trades_before = baseline_full["metrics"]["num_trades"]
    trades_after = meta_full["metrics"]["num_trades"]
    print(f"\nTrade count: {trades_before} (unfiltered) -> {trades_after} (meta-labeled, threshold={threshold})")
    if meta_full["metrics"]["sharpe_ratio"] > baseline_full["metrics"]["sharpe_ratio"] and meta_full["metrics"]["cagr_pct"] > baseline_full["metrics"]["cagr_pct"]:
        print("  Meta-labeling improved BOTH Sharpe and CAGR on TEST -- a genuinely promising filter, not just fewer trades.")
    else:
        print("  Meta-labeling did not clearly improve on the unfiltered baseline on this TEST data.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    parser.add_argument("--source", choices=["deriv", "yfinance"], default="yfinance")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()
    asyncio.run(main(args.granularity, args.source, args.threshold))

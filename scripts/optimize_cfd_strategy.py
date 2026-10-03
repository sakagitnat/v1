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
not an improvement, whatever its TRAIN numbers looked like. Ranking by
TRAIN calmar alone isn't enough either: the TRAIN-calmar #1 candidate
is evaluated on TEST like everything else, and can still lose to a
lower-ranked-on-TRAIN candidate that holds up better -- TOP_N_TO_TEST
candidates get evaluated on TEST, and whichever both clears the gate
and beats baseline, ranked by TEST calmar, wins (found this the hard
way: the TRAIN-calmar #1 candidate scored 35% TRAIN CAGR but -46% TEST
CAGR against a wider grid on ~2 years of data -- a catastrophic
overfit a naive "just take #1" selection would have missed).

Grid now includes adx_threshold (0/20/25) alongside the EMA/ATR
parameters -- an ADX chop filter (see strategy.py's docstring) skips
new entries when the market isn't trending strongly enough, aimed at
the ~46-50% win rate seen across every backtest so far: a plain EMA
crossover enters on sideways whipsaw as readily as a real trend, and
whipsaw entries are disproportionately losers. Same selection
discipline applies -- a nonzero adx_threshold is only adopted if it
clears the TRAIN gate AND beats baseline on TEST, exactly like any
other parameter combination; it doesn't get to skip the overfit check
just because the hypothesis behind it is intuitive.

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

--walk-forward N_FOLDS replaces the single TRAIN/TEST split above with
N_FOLDS of anchored walk-forward validation instead (see
trading.cfd.walk_forward's module docstring for the full methodology
and why a single split can't catch what this catches) -- costs several
times longer to run (the same grid search repeats once per fold on a
growing TRAIN window), which is why it's opt-in, not the default.

Usage: python scripts/optimize_cfd_strategy.py [--granularity 900] [--source deriv|yfinance] [--walk-forward N_FOLDS]
"""
import argparse
import asyncio
import itertools
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.broker import DerivBroker
from trading.cfd.deflated_sharpe import annualized_to_per_period, deflated_sharpe_ratio
from trading.cfd.strategy import EmaCrossoverStrategy
from trading.cfd.walk_forward import run_walk_forward
from trading.config import settings

CHUNK_COUNT = 5000  # Deriv's approx per-request cap for ticks_history
CHUNKS_PER_INSTRUMENT = 8  # up to 8 requests per instrument, paged backward

TRAIN_FRACTION = 0.7  # proportional, not fixed calendar dates -- history depth isn't known ahead of a live fetch
MIN_TRADES = 20  # ignore combos too thin to trust their metrics
MAX_DRAWDOWN_CAP = -25.0  # reject any combo whose TRAIN or TEST max drawdown is worse than this
TOP_N_TO_TEST = 10  # how many TRAIN-qualified candidates to also evaluate on TEST, not just the TRAIN-calmar winner

PARAM_GRID = {
    # Widened after the first ~2-year yfinance run: defaults (12/26/1.5/2.5)
    # traded 1157 times in TRAIN alone with a 34% win rate and -64% max
    # drawdown -- looks like whipsaw in ranging FX/gold, not a parameter
    # that just needs fine-tuning. This grid leans toward slower, less
    # noise-sensitive configs (wider EMA separation, wider stops) to test
    # that hypothesis, instead of searching near the same failing region.
    "fast_span": [10, 15, 21],
    "slow_span": [34, 50, 65],
    "atr_stop_mult": [1.5, 2.0, 3.0],
    "atr_target_mult": [2.0, 3.0, 4.5],
    # ADX chop filter (see strategy.py's docstring): 0 disables it
    # (backward-compatible baseline); 20/25 are Wilder's own commonly
    # cited "trending" thresholds, included to test directly whether
    # skipping low-ADX entries raises win rate rather than assuming it.
    "adx_threshold": [0, 20, 25],
}

# Yahoo Finance ticker candidates per Deriv instrument, tried in order --
# not the same vendor/feed as Deriv, so treat as a directional proxy.
YFINANCE_TICKERS = {
    "frxEURUSD": ["EURUSD=X"],
    "frxGBPUSD": ["GBPUSD=X"],
    "frxUSDJPY": ["USDJPY=X", "JPY=X"],
    "frxXAUUSD": ["XAUUSD=X", "GC=F"],
}
YFINANCE_INTERVAL_BY_GRANULARITY = {900: "15m", 1800: "30m", 3600: "1h", 14400: "4h", 86400: "1d"}
YFINANCE_PERIOD_BY_INTERVAL = {"15m": "60d", "30m": "60d", "1h": "730d", "1d": "10y"}


def fetch_history_yfinance(instrument: str, interval: str) -> pd.DataFrame:
    import yfinance as yf

    # Yahoo Finance has no native 4-hour bar -- fetch native 1h bars and
    # resample, rather than silently substituting a different granularity's
    # candles the way YFINANCE_INTERVAL_BY_GRANULARITY.get(..., "1h")'s
    # fallback used to for every unmapped granularity (900/3600/86400 were
    # the only entries until the 4-timeframe champion-account work needed
    # 1800/14400 too) -- the same class of bug lab_collector's
    # _strategy_for_tag() had: validating a strategy against candles it
    # will never actually see live.
    fetch_interval = "1h" if interval == "4h" else interval
    period = YFINANCE_PERIOD_BY_INTERVAL.get(fetch_interval, "730d")
    candidates = YFINANCE_TICKERS.get(instrument, [])
    if not candidates:
        print(f"  no known yfinance ticker mapping for {instrument} -- skipping")
        return pd.DataFrame(columns=["open", "high", "low", "close"])

    for ticker in candidates:
        df = yf.download(ticker, period=period, interval=fetch_interval, progress=False, auto_adjust=True)
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
        if interval == "4h":
            out = out.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
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


def run_backtest_full(strategy_kwargs: dict, bars: dict, strategy_cls=EmaCrossoverStrategy) -> dict:
    """Full engine output (equity_curve, trades, metrics) -- needed for
    the Deflated Sharpe Ratio inputs (per-bar return distribution's
    skew/kurtosis, observation count), not just the summary metrics the
    grid search loop below cares about. strategy_cls defaults to
    EmaCrossoverStrategy for this module's own callers, but every
    sibling optimize_cfd_*.py script reuses this (and report_dsr below)
    for its own strategy class via the strategy_cls argument, rather
    than re-implementing the same engine-wiring/DSR plumbing per file."""
    strategy = strategy_cls(**strategy_kwargs)
    engine = CfdBacktestEngine(
        strategy=strategy,
        starting_equity=10_000.0,
        risk_per_trade=settings.cfd_risk_per_trade,
        max_open_positions=settings.cfd_max_open_positions,
        max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
        spread_pct=settings.cfd_backtest_spread_pct,
        daily_financing_pct=settings.cfd_backtest_daily_financing_pct,
    )
    return engine.run(bars)


def run_backtest(strategy_kwargs: dict, bars: dict, strategy_cls=EmaCrossoverStrategy) -> dict:
    return run_backtest_full(strategy_kwargs, bars, strategy_cls)["metrics"]


def _periods_per_year(equity_curve: pd.Series) -> float:
    """Mirrors trading.cfd.backtest.compute_cfd_metrics' own annualization
    basis -- needed here to convert its annualized Sharpe back to the
    per-period Sharpe deflated_sharpe_ratio() requires."""
    if len(equity_curve) < 2:
        return 0.0
    elapsed_days = (equity_curve.index[-1] - equity_curve.index[0]).total_seconds() / 86400
    years = max(elapsed_days / 365.25, 1e-9)
    return len(equity_curve) / years


def _return_distribution_stats(equity_curve: pd.Series) -> tuple[int, float, float]:
    """(n_obs, skew, kurtosis) of the equity curve's per-bar returns --
    kurtosis here is raw (normal == 3.0), not pandas' excess convention
    (normal == 0.0), to match deflated_sharpe_ratio()'s expected input."""
    returns = equity_curve.pct_change().dropna()
    n_obs = len(returns)
    if n_obs < 3:
        return n_obs, 0.0, 3.0
    skew = returns.skew()
    kurt = returns.kurt() + 3.0
    if pd.isna(skew) or pd.isna(kurt):
        return n_obs, 0.0, 3.0
    return n_obs, float(skew), float(kurt)


def report_dsr(
    label: str,
    kwargs: dict,
    bars: dict,
    sr_std_per_period: float,
    n_trials: int,
    strategy_cls=EmaCrossoverStrategy,
) -> None:
    """Prints the Deflated Sharpe Ratio for one specific, already-chosen
    candidate (the recommended combo, or the untouched baseline when
    nothing was recommended) -- never for every grid combo, which would
    just be p-hacking the multiple-testing correction itself."""
    full = run_backtest_full(kwargs, bars, strategy_cls)
    curve = full["equity_curve"]
    ppy = _periods_per_year(curve)
    n_obs, skew, kurt = _return_distribution_stats(curve)
    per_period_sr = annualized_to_per_period(full["metrics"]["sharpe_ratio"], ppy)
    dsr = deflated_sharpe_ratio(
        observed_sr=per_period_sr,
        sr_trials_std=sr_std_per_period,
        n_trials=n_trials,
        n_obs=n_obs,
        skew=skew,
        kurtosis=kurt,
    )
    verdict = "nan (degenerate skew/kurtosis for this SR)" if dsr != dsr else f"{dsr:.1%}"
    print(
        f"\nDeflated Sharpe Ratio ({label}, {n_trials} trials searched, "
        f"TRAIN sharpe={full['metrics']['sharpe_ratio']:.2f} annualized): {verdict}"
    )
    print(
        "  P(true Sharpe exceeds what the best of this many noisy parameter "
        "combinations would be expected to produce by chance alone). "
        "Below ~95% means this result doesn't clearly look like skill rather "
        "than the winner of a multiple-testing lottery -- a separate check "
        "from the TRAIN/TEST gate above, which this can fail even when "
        "TRAIN/TEST passes."
    )


def _default_ema_combo_filter(values: tuple) -> bool:
    return values[0] < values[1]  # fast_span < slow_span, or the "crossover" is meaningless


def select_best_on_train(
    train_bars: dict,
    strategy_cls=EmaCrossoverStrategy,
    param_grid: dict = None,
    combo_filter=_default_ema_combo_filter,
) -> tuple[dict, dict]:
    """One TRAIN-only grid search and selection -- the half of main()'s
    logic that doesn't need a TEST split at all (TRAIN-side MIN_TRADES/
    CAGR>0/drawdown-cap filter, ranked by TRAIN calmar). Used both as
    part of main()'s own single-split flow conceptually, and directly
    as the select_fn walk-forward validation needs per fold (see
    trading.cfd.walk_forward's module docstring) -- each fold's own
    held-out TEST slice is what stands in for the single-split version's
    TEST-side robustness check, not a second check inside this
    function. Falls back to the untouched defaults ({}, baseline
    metrics) when nothing qualifies, same as main()'s own "keep current
    defaults" path.

    param_grid/combo_filter default to this module's own EmaCrossoverStrategy
    grid/constraint, but every sibling optimize_cfd_*.py script reuses this
    function for its own strategy by passing its own PARAM_GRID and combo
    constraint (e.g. optimize_cfd_breakout.py's entry_window > exit_window)
    rather than re-implementing this same TRAIN-only selection loop."""
    param_grid = PARAM_GRID if param_grid is None else param_grid
    keys = list(param_grid.keys())
    combos = [dict(zip(keys, values)) for values in itertools.product(*param_grid.values()) if combo_filter(values)]

    results = []
    for kwargs in combos:
        m = run_backtest(kwargs, train_bars, strategy_cls)
        if m["num_trades"] < MIN_TRADES:
            continue
        results.append((kwargs, m))

    pool = [r for r in results if r[1]["cagr_pct"] > 0 and r[1]["max_drawdown_pct"] >= MAX_DRAWDOWN_CAP]
    if not pool:
        return {}, run_backtest({}, train_bars, strategy_cls)

    pool.sort(key=lambda r: calmar(r[1]), reverse=True)
    return pool[0]


def print_walk_forward_report(report, strategy_cls=EmaCrossoverStrategy) -> None:
    print(f"\n=== Walk-forward validation: {report.n_folds} folds (anchored/expanding TRAIN) ===")
    for f in report.folds:
        verdict = "beat baseline" if f.beat_baseline else "did not beat baseline"
        print(f"  Fold {f.fold}: {f.kwargs}")
        print(f"    TRAIN {fmt(f.train_metrics)}")
        print(f"    TEST  {fmt(f.test_metrics)}  [{verdict}]")

    print(f"\nAcross all {report.n_folds} folds' TEST windows:")
    print(f"  mean CAGR:   {report.mean_test('cagr_pct'):.1f}%")
    print(f"  mean Sharpe: {report.mean_test('sharpe_ratio'):.2f}")
    print(f"  worst CAGR:  {report.worst_test('cagr_pct'):.1f}%")
    print(f"  worst drawdown: {report.worst_test('max_drawdown_pct'):.1f}%")
    print(f"  fraction of folds beating baseline: {report.fraction_beating_baseline():.0%}")

    stability = report.param_stability()
    stable = {k: v for k, v in stability.items() if len(v) == 1}
    unstable = {k: v for k, v in stability.items() if len(v) > 1}
    if unstable:
        print(
            f"  UNSTABLE parameters across folds (different value won each fold -- a red flag "
            f"a single TRAIN/TEST split can't see): {unstable}"
        )
    if stable:
        print(f"  Stable parameters (same value won every fold): { {k: next(iter(v)) for k, v in stable.items()} }")

    if report.fraction_beating_baseline() >= 0.7 and not unstable:
        print(
            "\n  Consistently beats baseline across folds with stable winning parameters -- "
            "genuine evidence of an edge, not a single-split artifact."
        )
    else:
        print(
            "\n  Does not consistently beat baseline and/or its winning parameters aren't stable "
            "across folds -- the single-split version's result (if any) looks more like this "
            "fold sequence's noise than a robust edge."
        )


def split(bars: dict[str, pd.DataFrame]) -> tuple[dict, dict]:
    train, test = {}, {}
    for sym, df in bars.items():
        cut = int(len(df) * TRAIN_FRACTION)
        train[sym] = df.iloc[:cut]
        test[sym] = df.iloc[cut:]
    return train, test


async def main(granularity_seconds: int, source: str, walk_forward_folds: int = 0):
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

    if walk_forward_folds > 0:
        report = run_walk_forward(
            bars,
            n_folds=walk_forward_folds,
            select_fn=select_best_on_train,
            evaluate_fn=run_backtest,
        )
        print_walk_forward_report(report)
        return

    train_bars, test_bars = split(bars)
    train_start = min(df.index[0] for df in train_bars.values() if not df.empty)
    train_end = max(df.index[-1] for df in train_bars.values() if not df.empty)
    print(f"\nTRAIN: {train_start} to {train_end} ({TRAIN_FRACTION:.0%} of fetched bars per instrument)")

    baseline_train_full = run_backtest_full({}, train_bars)
    baseline_train = baseline_train_full["metrics"]
    baseline_test = run_backtest({}, test_bars)
    print("\nBaseline (default EmaCrossoverStrategy params):")
    print(f"  TRAIN {fmt(baseline_train)}")
    print(f"  TEST  {fmt(baseline_test)}")

    # Same TRAIN date range for every combo below (the grid search varies
    # the strategy, not the bars), so this is a one-time computation --
    # needed to de-annualize each combo's Sharpe for the DSR inputs below.
    periods_per_year = _periods_per_year(baseline_train_full["equity_curve"])

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

    # Cross-sectional spread of this grid's own TRAIN Sharpe ratios --
    # the "how noisy is a single trial" input the Deflated Sharpe Ratio
    # needs to tell a genuinely good result apart from the best of many
    # mediocre ones. Trials below MIN_TRADES are excluded here (no
    # meaningful Sharpe to contribute) even though len(combos) -- the
    # true trial count passed to report_dsr -- still counts them: they
    # were still hypotheses this search tried, just ones estimated from
    # too few trades to say anything.
    trial_sharpes_per_period = [annualized_to_per_period(m["sharpe_ratio"], periods_per_year) for _, m in results]
    sr_std_per_period = statistics.pstdev(trial_sharpes_per_period) if len(trial_sharpes_per_period) >= 2 else 0.0

    pool = [r for r in results if r[1]["cagr_pct"] > 0 and r[1]["max_drawdown_pct"] >= MAX_DRAWDOWN_CAP]
    pool.sort(key=lambda r: calmar(r[1]), reverse=True)
    print(
        f"\nTop {TOP_N_TO_TEST} by TRAIN calmar (cagr/|maxdd|) among combos with CAGR > 0 "
        f"and drawdown no worse than {MAX_DRAWDOWN_CAP}% ({len(pool)}/{len(results)} qualify):"
    )
    for kwargs, m in pool[:TOP_N_TO_TEST]:
        print(f"  calmar={calmar(m):.2f}  {kwargs} -> {fmt(m)}")

    if not pool:
        print(f"\nNo combination qualified (min {MIN_TRADES} trades, CAGR>0, drawdown cap). Keeping current defaults.")
        report_dsr("baseline (kept)", {}, train_bars, sr_std_per_period, len(combos))
        return

    # Ranking by TRAIN calmar alone picks whichever combo best fit TRAIN's
    # noise -- evaluate the top N on TEST too, and only ever recommend one
    # that ALSO clears the gate and beats baseline out-of-sample. Ranking
    # the survivors by TEST calmar, not TRAIN calmar, so a worse-on-TRAIN
    # but genuinely-robust-on-TEST candidate can still win.
    print(f"\nEvaluating top {min(TOP_N_TO_TEST, len(pool))} TRAIN candidates on TEST...")
    robust = []
    for kwargs, train_m in pool[:TOP_N_TO_TEST]:
        test_m = run_backtest(kwargs, test_bars)
        overfit = test_m["cagr_pct"] <= 0 or test_m["max_drawdown_pct"] < MAX_DRAWDOWN_CAP
        underperforms_baseline = test_m["cagr_pct"] < baseline_test["cagr_pct"]
        verdict = "OVERFIT" if overfit else ("UNDERPERFORMS BASELINE" if underperforms_baseline else "ROBUST")
        print(f"  {kwargs}\n    TRAIN {fmt(train_m)}\n    TEST  {fmt(test_m)}  [{verdict}]")
        if not overfit and not underperforms_baseline:
            robust.append((kwargs, train_m, test_m))

    if not robust:
        print(
            "\n  None of the top candidates hold up out-of-sample and beat the default params on TEST. "
            "NOT recommending any change -- keep the current defaults."
        )
        report_dsr("baseline (kept)", {}, train_bars, sr_std_per_period, len(combos))
        return

    robust.sort(key=lambda r: calmar(r[2]), reverse=True)
    best_kwargs, best_train, best_test = robust[0]
    print(f"\n=== Recommended: {best_kwargs} ===")
    print(f"  TRAIN {fmt(best_train)}")
    print(f"  TEST  {fmt(best_test)}")
    print("\n  Holds up out-of-sample and beats the default params on TEST -- recommended.")
    report_dsr("recommended candidate", best_kwargs, train_bars, sr_std_per_period, len(combos))


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
    parser.add_argument(
        "--walk-forward",
        type=int,
        default=0,
        metavar="N_FOLDS",
        help="Run N_FOLDS of anchored walk-forward validation (see trading.cfd.walk_forward's module "
        "docstring) instead of the default single TRAIN/TEST split. 0 (default) keeps the single-split "
        "behavior.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.granularity, args.source, args.walk_forward))

"""Ranging-regime diagnostic -- scripts/diagnose_cfd_regime.py

Three structurally distinct "ranging" strategies (`mean_reversion@v1`,
`rsi_reversion@v1`, `support_resistance@v1`) have now all been honestly
RETIRED after real TRAIN/TEST grid searches -- see docs/
ARCHITECTURE_AUDIT.md gap #11. All three shared one unexamined
assumption: that `trading.cfd.regime`'s RANGING label means "price
reverts toward a level/mean," and built a fade around that. Before
building a fourth strategy on the same assumption, this script checks
whether the assumption itself holds -- per the joint Claude/GPT design
discussion on GitHub issue #5, which asked for exactly this: "is the
strategy family wrong, or is the current 'ranging' label grouping
together multiple different market structures?"

This is deliberately NOT a strategy or a backtest -- it fits no
parameters and reports no CAGR. It's descriptive statistics about what
`classify_regime()` actually labels RANGING on real data:
  1. how much of each instrument's history is RANGING (vs TRENDING/
     UNSTABLE/UNKNOWN), broken down by instrument and by rough session
     (Asian/London/NY/Late, UTC-hour buckets -- an approximation, not a
     precise session-boundary claim),
  2. how long a RANGING episode typically lasts, and what regime it
     tends to transition into when it ends,
  3. what actually happens to price after a RANGING episode starts --
     forward return and max favorable/adverse excursion over several
     horizons, with NO trading logic applied -- split by the ATR%
     volatility bucket (classify_volatility_series) at the episode's
     start, to check whether RANGING is mixing genuinely quiet
     (LOW-volatility) ranges with pre-breakout compression (a LOW-vol
     entry followed by volatility expansion) or noisy chop
     (NORMAL/HIGH-vol entry with no net drift either way) -- three
     different structures a single fade strategy has no business
     treating identically.

Uses trading.cfd.regime's classify_regime_series()/
classify_volatility_series() (vectorized siblings of the live, last-
bar-only classify_regime()/classify_volatility() -- added alongside
this script specifically for this kind of per-bar research; neither is
used by any live decision path). Reuses optimize_cfd_strategy.py's
fetch_history_yfinance() -- same proxy feed, same instruments, no new
data dependency.

Full history is used (no TRAIN/TEST split): this script fits no
parameters to the data, so there's nothing here that could overfit --
splitting it would only throw away statistical power on a purely
descriptive question.

Needs a live network connection -- run via the "CFD Manual Command"
GitHub Actions workflow (command=diagnose-regime) and read its job logs.

Usage: python scripts/diagnose_cfd_regime.py [--granularity 3600]
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from trading.cfd.regime import (
    RANGING,
    TRENDING,
    UNKNOWN,
    UNSTABLE,
    VOLATILITY_UNKNOWN,
    classify_regime_series,
    classify_volatility_series,
)
from trading.config import settings

from optimize_cfd_strategy import YFINANCE_INTERVAL_BY_GRANULARITY, fetch_history_yfinance

FORWARD_HORIZONS = [5, 10, 20]  # bars ahead, at whatever granularity was fetched (H1 by default)

SESSION_BOUNDS_UTC = [  # rough UTC-hour buckets, not a precise session-boundary claim -- see docstring
    (0, 7, "Asian"),
    (7, 13, "London"),
    (13, 21, "NY"),
    (21, 24, "Late"),
]


def _session(hour: int) -> str:
    for lo, hi, name in SESSION_BOUNDS_UTC:
        if lo <= hour < hi:
            return name
    return "Late"


@dataclass
class Episode:
    label: str
    start_pos: int
    end_pos: int

    @property
    def length(self) -> int:
        return self.end_pos - self.start_pos + 1


def _episodes(labels: np.ndarray) -> list[Episode]:
    """Contiguous same-label runs, by integer position (not timestamp --
    gaps like weekends don't matter for "how many bars did this episode
    last")."""
    if len(labels) == 0:
        return []
    change_points = np.flatnonzero(labels[1:] != labels[:-1]) + 1
    starts = np.concatenate(([0], change_points))
    ends = np.concatenate((change_points - 1, [len(labels) - 1]))
    return [Episode(label=labels[s], start_pos=s, end_pos=e) for s, e in zip(starts, ends)]


def _pct(count: int, total: int) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def _percentile(values: list[float], p: float) -> float:
    return round(float(np.percentile(values, p)), 1) if values else float("nan")


def report_composition(instrument: str, regime: pd.Series) -> None:
    total = len(regime)
    print(f"\n  Regime composition ({total} bars):")
    for label in (TRENDING, RANGING, UNSTABLE, UNKNOWN):
        count = int((regime == label).sum())
        print(f"    {label:<10} {count:>6} bars ({_pct(count, total)}%)")

    sessions = pd.Series([_session(ts.hour) for ts in regime.index], index=regime.index)
    print("  Regime composition by session:")
    for _, _, name in [(0, 7, "Asian"), (7, 13, "London"), (13, 21, "NY"), (21, 24, "Late")]:
        mask = sessions == name
        session_total = int(mask.sum())
        if session_total == 0:
            continue
        ranging_pct = _pct(int(((regime == RANGING) & mask).sum()), session_total)
        trending_pct = _pct(int(((regime == TRENDING) & mask).sum()), session_total)
        print(f"    {name:<8} ranging={ranging_pct}%  trending={trending_pct}%  ({session_total} bars)")


def report_persistence_and_transitions(instrument: str, episodes: list[Episode]) -> None:
    print("  Episode persistence (bars per episode):")
    for label in (TRENDING, RANGING, UNSTABLE):
        lengths = [e.length for e in episodes if e.label == label]
        if not lengths:
            print(f"    {label:<10} no episodes")
            continue
        print(
            f"    {label:<10} n={len(lengths):>4}  mean={np.mean(lengths):.1f}  "
            f"median={np.median(lengths):.1f}  p90={_percentile(lengths, 90)}"
        )

    ranging_transitions: dict[str, int] = {}
    for i, ep in enumerate(episodes):
        if ep.label != RANGING or i + 1 >= len(episodes):
            continue
        next_label = episodes[i + 1].label
        ranging_transitions[next_label] = ranging_transitions.get(next_label, 0) + 1
    total_transitions = sum(ranging_transitions.values())
    if total_transitions:
        print("  What a RANGING episode transitions into when it ends:")
        for label, count in sorted(ranging_transitions.items(), key=lambda kv: -kv[1]):
            print(f"    -> {label:<10} {_pct(count, total_transitions)}% ({count}/{total_transitions})")


def report_forward_stats(instrument: str, close: pd.Series, episodes: list[Episode], volatility: pd.Series) -> None:
    print("  Forward price behavior after a RANGING episode STARTS (no trading logic, pure price):")
    ranging_starts = [e.start_pos for e in episodes if e.label == RANGING]
    close_vals = close.to_numpy()
    atr_pct_proxy = None  # computed lazily below only if needed for the expansion check

    by_vol_bucket: dict[str, list[int]] = {}
    for pos in ranging_starts:
        bucket = volatility.iloc[pos] if pos < len(volatility) else VOLATILITY_UNKNOWN
        by_vol_bucket.setdefault(bucket, []).append(pos)

    for horizon in FORWARD_HORIZONS:
        print(f"    horizon={horizon} bars:")
        for bucket, positions in sorted(by_vol_bucket.items()):
            fwd_returns, mfe, mae = [], [], []
            for pos in positions:
                end = pos + horizon
                if end >= len(close_vals):
                    continue
                entry = close_vals[pos]
                window = close_vals[pos : end + 1]
                fwd_returns.append((window[-1] / entry - 1) * 100)
                mfe.append((window.max() / entry - 1) * 100)
                mae.append((window.min() / entry - 1) * 100)
            if not fwd_returns:
                continue
            print(
                f"      entry_vol={bucket:<8} n={len(fwd_returns):>4}  "
                f"mean_fwd_ret={np.mean(fwd_returns):+.2f}%  "
                f"mean_MFE={np.mean(mfe):+.2f}%  mean_MAE={np.mean(mae):+.2f}%"
            )


def main(granularity_seconds: int) -> None:
    interval = YFINANCE_INTERVAL_BY_GRANULARITY.get(granularity_seconds, "1h")
    print(f"Fetching from yfinance (interval={interval}, a proxy feed -- see optimize_cfd_strategy.py's docstring)...")

    for instrument in settings.cfd_instruments:
        df = fetch_history_yfinance(instrument, interval)
        if df.empty or len(df) < 200:
            print(f"\n=== {instrument}: insufficient history ({len(df)} bars) -- skipping ===")
            continue

        print(f"\n=== {instrument}: {len(df)} bars, {df.index[0]} to {df.index[-1]} ===")
        regime = classify_regime_series(df)
        volatility = classify_volatility_series(df)
        episodes = _episodes(regime.to_numpy())

        report_composition(instrument, regime)
        report_persistence_and_transitions(instrument, episodes)
        report_forward_stats(instrument, df["close"], episodes, volatility)

    print(
        "\n=== Read this against issue #5's question: does RANGING mean one thing, or several? ===\n"
        "If mean_fwd_ret/MFE/MAE look similar across volatility buckets and instruments, the label is\n"
        "probably one coherent structure and the three retired fades failed for some other reason (params,\n"
        "cost model, instrument choice). If LOW-volatility-entry episodes show materially different forward\n"
        "behavior (bigger MFE/MAE spread, directional drift) than NORMAL/HIGH-volatility-entry episodes, that's\n"
        "evidence RANGING is mixing genuine quiet consolidation with pre-breakout compression -- and a\n"
        "volatility-expansion/breakout-transition strategy, not another fade, is the next candidate to build."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--granularity", type=int, default=3600)
    args = parser.parse_args()
    main(args.granularity)

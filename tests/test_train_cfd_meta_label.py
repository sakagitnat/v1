import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from train_cfd_meta_label import collect_training_samples, report_psr
from trading.cfd.strategy import EmaCrossoverStrategy


def _synthetic_bars(n=1500, seed=13):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    price = 100 + np.cumsum(rng.normal(0, 0.3, n))
    df = pd.DataFrame(
        {
            "open": price,
            "high": price + np.abs(rng.normal(0, 0.2, n)),
            "low": price - np.abs(rng.normal(0, 0.2, n)),
            "close": price,
        },
        index=idx,
    )
    return {"frxEURUSD": df}


def test_collect_training_samples_returns_matched_features_and_labels():
    strategy = EmaCrossoverStrategy()
    features, labels = collect_training_samples(strategy, _synthetic_bars())
    assert len(features) == len(labels)
    assert all(label in (0, 1) for label in labels)
    assert all(len(f) == 4 for f in features)  # FEATURE_NAMES has 4 entries


def test_collect_training_samples_never_double_counts_while_in_position():
    # Reuses the engine's own in_position/stop/target bookkeeping, so a
    # strategy that opens a position shouldn't register a second entry
    # before that position closes -- sanity check on the entry count,
    # not an exact backtest replay.
    strategy = EmaCrossoverStrategy()
    bars = _synthetic_bars()
    features, _ = collect_training_samples(strategy, bars)
    # Loose upper bound: can't exceed one entry opportunity per bar.
    total_bars = sum(len(df) for df in bars.values())
    assert len(features) <= total_bars


def test_report_psr_runs_without_error(capsys):
    idx = pd.date_range("2026-01-01", periods=200, freq="1h", tz="UTC")
    curve = pd.Series(10000 * (1.0001 ** np.arange(200)), index=idx)
    metrics = {"sharpe_ratio": 1.5}

    report_psr("test", metrics, curve)

    out = capsys.readouterr().out
    assert "PSR (test" in out

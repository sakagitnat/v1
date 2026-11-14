import numpy as np
import pandas as pd
import pytest

from trading.cfd.meta_label import LogisticRegression, extract_features, triple_barrier_label


def _bars(rows, start="2026-01-01"):
    idx = pd.date_range(start, periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, index=idx)


def test_triple_barrier_long_hits_target_first():
    future = _bars(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100.5},
            {"open": 100.5, "high": 106, "low": 100, "close": 105},  # pierces target=105
        ]
    )
    label = triple_barrier_label("long", entry_price=100, stop_price=95, target_price=105, future_bars=future, max_holding_bars=10)
    assert label == 1


def test_triple_barrier_long_hits_stop_first():
    future = _bars(
        [
            {"open": 100, "high": 101, "low": 94, "close": 95},  # pierces stop=95 on bar 1
            {"open": 95, "high": 110, "low": 94, "close": 109},  # would've hit target later -- too late
        ]
    )
    label = triple_barrier_label("long", entry_price=100, stop_price=95, target_price=105, future_bars=future, max_holding_bars=10)
    assert label == 0


def test_triple_barrier_short_hits_target_first():
    future = _bars([{"open": 100, "high": 101, "low": 94, "close": 95}])  # low pierces target=95 for a short
    label = triple_barrier_label("short", entry_price=100, stop_price=105, target_price=95, future_bars=future, max_holding_bars=10)
    assert label == 1


def test_triple_barrier_neither_hit_uses_vertical_barrier_favorable():
    future = _bars([{"open": 100, "high": 102, "low": 99, "close": 102}])  # never reaches stop=90 or target=120
    label = triple_barrier_label("long", entry_price=100, stop_price=90, target_price=120, future_bars=future, max_holding_bars=1)
    assert label == 1  # closed above entry -- favorable to a long


def test_triple_barrier_neither_hit_uses_vertical_barrier_unfavorable():
    future = _bars([{"open": 100, "high": 101, "low": 98, "close": 98}])
    label = triple_barrier_label("long", entry_price=100, stop_price=90, target_price=120, future_bars=future, max_holding_bars=1)
    assert label == 0  # closed below entry -- unfavorable to a long


def test_triple_barrier_both_hit_same_bar_is_conservative():
    future = _bars([{"open": 100, "high": 106, "low": 94, "close": 100}])  # both stop=95 and target=105 pierced
    label = triple_barrier_label("long", entry_price=100, stop_price=95, target_price=105, future_bars=future, max_holding_bars=10)
    assert label == 0  # assume the adverse outcome, not the favorable one


def test_triple_barrier_insufficient_future_data_returns_none():
    label = triple_barrier_label("long", entry_price=100, stop_price=95, target_price=105, future_bars=_bars([]), max_holding_bars=10)
    assert label is None


def test_extract_features_scale_free_ratios():
    row = pd.Series({"close": 100.0, "adx": 25.0, "atr": 2.0, "fast_ema": 101.0, "slow_ema": 99.0})
    features = extract_features(row)
    assert features[0] == 25.0  # adx passed through
    assert features[1] == pytest.approx(0.02)  # atr_pct = 2/100
    assert features[2] == pytest.approx(0.02)  # ema_spread_pct = (101-99)/100
    assert features[3] == pytest.approx(0.01)  # trend_distance_pct = (100-99)/100


def test_extract_features_handles_nan_adx():
    row = pd.Series({"close": 100.0, "adx": float("nan"), "atr": 1.0, "fast_ema": 100.0, "slow_ema": 100.0})
    features = extract_features(row)
    assert features[0] == 0.0


def test_logistic_regression_separates_linearly_separable_data():
    rng = np.random.default_rng(0)
    pos = rng.normal(loc=[2, 2], scale=0.3, size=(50, 2))
    neg = rng.normal(loc=[-2, -2], scale=0.3, size=(50, 2))
    X = np.vstack([pos, neg])
    y = np.concatenate([np.ones(50), np.zeros(50)])

    model = LogisticRegression(learning_rate=0.5, n_iter=500).fit(X, y)
    preds = model.predict_proba(X)

    accuracy = ((preds >= 0.5).astype(float) == y).mean()
    assert accuracy > 0.95


def test_logistic_regression_predict_proba_before_fit_raises():
    with pytest.raises(RuntimeError):
        LogisticRegression().predict_proba([[1.0, 2.0]])


def test_logistic_regression_output_is_a_probability():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(30, 3))
    y = rng.integers(0, 2, size=30).astype(float)
    model = LogisticRegression(n_iter=100).fit(X, y)
    probs = model.predict_proba(X)
    assert ((probs >= 0.0) & (probs <= 1.0)).all()

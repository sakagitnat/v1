"""Meta-labeling (Lopez de Prado, "Advances in Financial Machine
Learning", ch. 3): a secondary model that doesn't pick direction or
sizing -- the primary strategy (e.g. EmaCrossoverStrategy) still owns
that -- it only answers "is THIS specific signal, with these features,
worth taking at all?" Suppressing a bad entry is categorically safer
than inventing a new one: a meta-label filter can only ever reduce a
primary strategy's trade count, never add a position the primary
strategy itself wouldn't have opened, so it can't introduce a new kind
of risk the primary strategy's own stop/target logic doesn't already
bound.

No scikit-learn dependency (this project has never added one -- see
requirements.txt and src/trading/cfd/deflated_sharpe.py's own from-
scratch inverse-normal-CDF for the same reasoning): LogisticRegression
below is a minimal, from-scratch, numpy-only implementation, auditable
in a few dozen lines rather than a library's black box, which matters
more here than raw model capacity -- a meta-filter this project can't
inspect would undermine the exact "why did we trust this candidate"
discipline deflated_sharpe.py and the TRAIN/TEST gate both exist for.

Two independent pieces:
  - triple_barrier_label(): turns one primary-strategy entry into a
    ground-truth 1 (profitable) / 0 (not) by replaying what actually
    happened next -- did price reach the target first, the stop first,
    or neither within the holding horizon (in which case the label
    follows which side of entry price it ended up on).
  - LogisticRegression: fits P(label=1 | features) by gradient descent
    on standardized features, for scripts/train_cfd_meta_label.py to
    train on triple_barrier_label() outcomes and
    MetaLabeledStrategy (meta_labeled_strategy.py) to query at signal
    time.
"""
import numpy as np
import pandas as pd

FEATURE_NAMES = ["adx", "atr_pct", "ema_spread_pct", "trend_distance_pct"]


def extract_features(row: pd.Series) -> list[float]:
    """Pulls meta-label features from a bar already prepared by
    EmaCrossoverStrategy.prepare() (fast_ema/slow_ema/atr/adx columns).
    All features are scale-free (percentages/ratios, not raw price or
    raw ATR) so the same trained model generalizes across instruments
    at very different price levels (XAUUSD vs. a JPY pair) -- the same
    reason CfdRiskManager sizes by risk fraction, not raw price
    distance.

    - adx: trend strength, independent of direction (already the
      strategy's own optional chop filter's signal, see strategy.py).
    - atr_pct: ATR as a fraction of price -- how volatile this
      instrument/moment is right now, not in absolute price units.
    - ema_spread_pct: fast-minus-slow EMA, as a fraction of price --
      how decisively "crossed" the signal is, not just that it crossed.
    - trend_distance_pct: price's distance from the slow EMA, as a
      fraction of price -- how extended the move already is (a fresh
      crossover right at the slow EMA looks different from one far
      past it)."""
    price = row["close"]
    return [
        float(row["adx"]) if pd.notna(row["adx"]) else 0.0,
        float(row["atr"]) / price if price else 0.0,
        (float(row["fast_ema"]) - float(row["slow_ema"])) / price if price else 0.0,
        (price - float(row["slow_ema"])) / price if price else 0.0,
    ]


def triple_barrier_label(
    side: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    future_bars: pd.DataFrame,
    max_holding_bars: int,
) -> int | None:
    """1 if `target_price` is reached before `stop_price` within the
    next `max_holding_bars` bars of `future_bars` (strictly after the
    entry bar -- callers pass bars.iloc[entry_idx + 1 :]); 0 if the
    stop is hit first. Neither hit within the horizon -> the vertical
    barrier: label follows whichever side of entry_price the last bar's
    close ended up on (1 if favorable to `side`, 0 if not -- a flat
    close is treated as 0, not a free win). None if future_bars has too
    few bars to judge at all (can't label the most recent signals near
    the end of a dataset -- callers should drop these, not guess)."""
    window = future_bars.iloc[:max_holding_bars]
    if window.empty:
        return None

    for _, bar in window.iterrows():
        hit_target = bar["high"] >= target_price if side == "long" else bar["low"] <= target_price
        hit_stop = bar["low"] <= stop_price if side == "long" else bar["high"] >= stop_price
        if hit_target and hit_stop:
            # Both inside the same bar -- conservative: assume the
            # adverse outcome, consistent with CfdBacktestEngine's own
            # stop-priority-unspecified bars never being assumed to
            # favor the trade.
            return 0
        if hit_target:
            return 1
        if hit_stop:
            return 0

    last_close = window.iloc[-1]["close"]
    favorable = last_close > entry_price if side == "long" else last_close < entry_price
    return 1 if favorable else 0


class LogisticRegression:
    """Minimal from-scratch binary logistic regression (batch gradient
    descent on L2-regularized cross-entropy), standardizing features
    internally so a single learning_rate works across differently-
    scaled inputs without per-feature tuning. See module docstring for
    why this isn't scikit-learn's."""

    def __init__(self, learning_rate: float = 0.1, l2: float = 0.01, n_iter: int = 1000):
        self.learning_rate = learning_rate
        self.l2 = l2
        self.n_iter = n_iter
        self.weights: np.ndarray | None = None
        self.bias: float = 0.0
        self._feature_mean: np.ndarray | None = None
        self._feature_std: np.ndarray | None = None

    def _standardize(self, X: np.ndarray) -> np.ndarray:
        std = np.where(self._feature_std == 0, 1.0, self._feature_std)
        return (X - self._feature_mean) / std

    def fit(self, X: np.ndarray, y: np.ndarray) -> "LogisticRegression":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        n_samples, n_features = X.shape

        self._feature_mean = X.mean(axis=0)
        self._feature_std = X.std(axis=0)
        Xs = self._standardize(X)

        self.weights = np.zeros(n_features)
        self.bias = 0.0

        for _ in range(self.n_iter):
            z = Xs @ self.weights + self.bias
            pred = 1.0 / (1.0 + np.exp(-z))
            error = pred - y
            grad_w = (Xs.T @ error) / n_samples + self.l2 * self.weights
            grad_b = error.mean()
            self.weights -= self.learning_rate * grad_w
            self.bias -= self.learning_rate * grad_b

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.weights is None:
            raise RuntimeError("LogisticRegression.fit() must be called before predict_proba()")
        Xs = self._standardize(np.asarray(X, dtype=float))
        z = Xs @ self.weights + self.bias
        return 1.0 / (1.0 + np.exp(-z))

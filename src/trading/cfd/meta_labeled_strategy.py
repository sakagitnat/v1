import pandas as pd

from trading.cfd.meta_label import LogisticRegression, extract_features
from trading.strategy.base import Action, Signal


class MetaLabeledStrategy:
    """Wraps another CFD strategy (prepare()/signal_for_row()
    interface) with a trained meta-label filter (see
    trading.cfd.meta_label module docstring): every signal the wrapped
    strategy would emit still comes from it unchanged -- this class
    never invents a direction, stop, or target of its own -- EXCEPT a
    NEW entry (a BUY/SELL while flat) is suppressed (downgraded to
    HOLD) if the meta-model's predicted probability it ends up
    profitable falls below `threshold`. An exit signal (closing an
    already-open position) is never filtered: suppressing an exit
    would leave an open position's risk unmanaged, which is exactly
    the kind of new risk a meta-label filter must not introduce (see
    module docstring).

    Built against EmaCrossoverStrategy specifically (extract_features()
    reads its prepare()-computed fast_ema/slow_ema/atr/adx columns),
    but nothing else here assumes that -- a future meta-labeled wrapper
    for another strategy only needs its own feature extractor passed
    the same way.
    """

    def __init__(
        self,
        base_strategy,
        model: LogisticRegression,
        threshold: float = 0.5,
        feature_fn=extract_features,
    ):
        self.base_strategy = base_strategy
        self.model = model
        self.threshold = threshold
        self.feature_fn = feature_fn

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        return self.base_strategy.prepare(bars)

    def signal_for_row(self, symbol: str, row: pd.Series, prev_row: pd.Series, in_position: str | None) -> Signal:
        signal = self.base_strategy.signal_for_row(symbol, row, prev_row, in_position)

        is_new_entry = in_position is None and signal.action in (Action.BUY, Action.SELL)
        if not is_new_entry:
            return signal

        features = self.feature_fn(row)
        probability = float(self.model.predict_proba([features])[0])
        if probability < self.threshold:
            return Signal(
                symbol,
                Action.HOLD,
                signal.price,
                reason=f"meta-label filtered (p={probability:.2f} < threshold={self.threshold:.2f}): {signal.reason}",
            )
        return signal

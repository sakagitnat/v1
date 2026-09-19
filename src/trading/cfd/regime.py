"""Market Regime Engine (CFD) -- src/trading/cfd/regime.py

Classifies an instrument's current regime from its own price action, one
instrument at a time -- unlike the stock system's trading.regime (a
single bull/bear/neutral read off one reference symbol, SPY, standing in
for "the market" as a whole). There's no equivalent single reference
instrument across forex pairs, gold, and Deriv's synthetic indices, so
each CFD instrument is classified from its own candles instead.

The taxonomy is deliberately narrow for now -- TRENDING vs RANGING vs
UNKNOWN (not enough data yet) -- because that's what the current strategy
pool can actually act on: both registered CFD strategies (ema_crossover,
donchian_breakout -- see trading.cfd.strategy_registry) are trend-
following, with no mean-reversion/range-trading strategy registered yet.
Adding richer regime dimensions (volatility level, multi-timeframe
alignment, etc.) ahead of a strategy that would actually use them would
just be unused complexity -- see docs/ARCHITECTURE_AUDIT.md's later
phases for what's still missing from the strategy pool.

Uses ADX (trend strength, direction-independent) -- the same indicator
EmaCrossoverStrategy's own optional chop filter already uses (see its
docstring) -- rather than introducing a second, different trend measure.
trend_threshold=25.0 is ADX's conventional textbook cutoff (Wilder's
original interpretation: below ~20 is a weak/no trend, above ~25 is
trending); this hasn't been walked through a TRAIN/TEST split the way
strategy parameters are (see docs/ARCHITECTURE_AUDIT.md) -- a reasonable,
sourced default, not yet a validated one.
"""
import pandas as pd

from trading.indicators import adx

TRENDING = "trending"
RANGING = "ranging"
UNKNOWN = "unknown"


def classify_regime(bars: pd.DataFrame, adx_window: int = 14, trend_threshold: float = 25.0) -> str:
    """Classifies the most recent bar's regime from the same raw OHLC
    history a strategy would see. Computed from raw bars, not a
    strategy's own prepared indicators, because regime classification has
    to happen *before* a strategy is even picked (trading.cfd.selector) --
    it can't depend on which one that turns out to be."""
    if len(bars) < adx_window + 1:
        return UNKNOWN
    adx_series = adx(bars["high"], bars["low"], bars["close"], adx_window)
    latest = adx_series.iloc[-1]
    if pd.isna(latest):
        return UNKNOWN
    return TRENDING if latest >= trend_threshold else RANGING

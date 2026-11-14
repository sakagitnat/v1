"""Market Regime Engine (CFD) -- src/trading/cfd/regime.py

Classifies an instrument's current regime from its own price action, one
instrument at a time -- unlike the stock system's trading.regime (a
single bull/bear/neutral read off one reference symbol, SPY, standing in
for "the market" as a whole). There's no equivalent single reference
instrument across forex pairs, gold, and Deriv's synthetic indices, so
each CFD instrument is classified from its own candles instead.

Two dimensions feed the classification: trend strength (ADX -- the same
indicator EmaCrossoverStrategy's own optional chop filter already uses)
and volatility (ATR as a fraction of price, compared against its own
recent history -- not an absolute threshold, since "normal" volatility
differs wildly across a forex pair, gold, and a Deriv synthetic index).
classify_regime() still returns a single string, same as before, so
every existing caller (trading.cfd.scheduler, trading.cfd.selector,
trading.cfd.paper_trading, trading.cfd.trade_log.TradeRecord.regime,
already-registered strategies' suited_regimes) keeps working unchanged --
TRENDING and RANGING mean exactly what they always did. What's new is
UNSTABLE: a volatility spike (current ATR% far above its own recent
normal, per CFD_REGIME_UNSTABLE_VOLATILITY_RATIO) without a clear trend
to justify the risk -- whipsaw/choppy conditions distinct from ordinary
RANGING (calm, unremarkable volatility, just no clear direction) that
the current trend-following strategy pool has no business trading either
way. No registered strategy declares suited_regimes=["unstable"], so
today this acts as another NO TRADE gate, same as RANGING did before any
range-trading strategy existed -- see docs/ARCHITECTURE_AUDIT.md.

classify_volatility() exposes the LOW/NORMAL/HIGH volatility read on its
own, informationally (e.g. for logging/manager_report) -- not yet
consumed by strategy selection, since no registered strategy declares a
volatility preference. Adding richer regime dimensions ahead of a
strategy that would actually use them is unused complexity in general
(see docs/ARCHITECTURE_AUDIT.md's earlier note on this), but UNSTABLE
earns its place because "don't trade during a volatility spike with no
trend" is itself the risk-reducing decision the current strategy pool
already implicitly needs -- it isn't waiting on a strategy that trades
UNSTABLE conditions, the same way RANGING isn't waiting on one either.

trend_threshold=25.0 is ADX's conventional textbook cutoff (Wilder's
original interpretation: below ~20 is a weak/no trend, above ~25 is
trending); this hasn't been walked through a TRAIN/TEST split the way
strategy parameters are (see docs/ARCHITECTURE_AUDIT.md) -- a reasonable,
sourced default, not yet a validated one. The volatility ratio
thresholds below are the same kind of reasonable-but-unvalidated default.
"""
import pandas as pd

from trading.indicators import atr as atr_indicator
from trading.indicators import adx

TRENDING = "trending"
RANGING = "ranging"
UNSTABLE = "unstable"
UNKNOWN = "unknown"

VOLATILITY_LOW = "low"
VOLATILITY_NORMAL = "normal"
VOLATILITY_HIGH = "high"
VOLATILITY_UNKNOWN = "unknown"

MIN_VOLATILITY_HISTORY = 10
"""Below this many valid ATR% readings, there's not enough of its own
history to judge "abnormal" against -- classify_volatility() reports
VOLATILITY_UNKNOWN and classify_regime() skips the UNSTABLE check
entirely (falls back to plain ADX-based TRENDING/RANGING) rather than
risk a false spike read off a handful of points."""


def _atr_pct_series(bars: pd.DataFrame, atr_window: int) -> pd.Series:
    atr_series = atr_indicator(bars["high"], bars["low"], bars["close"], atr_window)
    return (atr_series / bars["close"]).dropna()


def classify_volatility(
    bars: pd.DataFrame,
    atr_window: int = 14,
    lookback: int = 100,
    low_ratio: float = 0.6,
    high_ratio: float = 1.5,
) -> str:
    """Compares the latest bar's ATR% (average true range as a fraction of
    price) against the median ATR% over the trailing `lookback` valid
    readings -- a ratio, not an absolute cutoff, so this reads the same
    way on a low-price-volatility forex pair and a high-price-volatility
    synthetic index: both get judged against their OWN normal, not a
    fixed number. latest/median >= high_ratio is HIGH, <= low_ratio is
    LOW, otherwise NORMAL."""
    atr_pct = _atr_pct_series(bars, atr_window)
    if len(atr_pct) < MIN_VOLATILITY_HISTORY:
        return VOLATILITY_UNKNOWN
    history = atr_pct.iloc[-lookback:]
    median = history.median()
    if median <= 0:
        return VOLATILITY_UNKNOWN
    ratio = history.iloc[-1] / median
    if ratio >= high_ratio:
        return VOLATILITY_HIGH
    if ratio <= low_ratio:
        return VOLATILITY_LOW
    return VOLATILITY_NORMAL


def classify_volatility_series(
    bars: pd.DataFrame,
    atr_window: int = 14,
    lookback: int = 100,
    low_ratio: float = 0.6,
    high_ratio: float = 1.5,
) -> pd.Series:
    """Vectorized sibling of classify_volatility(): the same latest/
    trailing-median-ratio logic, evaluated at every bar instead of just
    the most recent one. Exists for research/diagnostic use (e.g.
    scripts/diagnose_cfd_regime.py's regime-substructure analysis) where
    the per-bar history is needed, not just today's read -- not used by
    any live decision path, which only ever needs "right now" and keeps
    calling classify_volatility(). `.rolling(lookback).median()` is the
    honest bar-by-bar equivalent of classify_volatility()'s `iloc[
    -lookback:].median()` when called at successive live bars: at each
    point it only looks backward, so this carries no more lookahead than
    the live function already doesn't have."""
    # _atr_pct_series() dropna()s the leading atr_window warmup bars, so
    # it's shorter than bars.index -- build the result on ITS index (the
    # only one every other series here shares) and reindex onto the full
    # bars.index only at the end, rather than mixing a shorter boolean
    # mask into a full-length Series (misaligned index -> pandas raises).
    atr_pct = _atr_pct_series(bars, atr_window)
    median = atr_pct.rolling(lookback, min_periods=MIN_VOLATILITY_HISTORY).median()
    ratio = atr_pct / median
    result = pd.Series(VOLATILITY_UNKNOWN, index=atr_pct.index)
    valid = median.notna() & (median > 0)
    result.loc[valid & (ratio >= high_ratio)] = VOLATILITY_HIGH
    result.loc[valid & (ratio <= low_ratio)] = VOLATILITY_LOW
    result.loc[valid & (ratio > low_ratio) & (ratio < high_ratio)] = VOLATILITY_NORMAL
    return result.reindex(bars.index, fill_value=VOLATILITY_UNKNOWN)


def classify_regime_series(
    bars: pd.DataFrame,
    adx_window: int = 14,
    trend_threshold: float = 25.0,
    atr_window: int = 14,
    volatility_lookback: int = 100,
    unstable_volatility_ratio: float = 2.5,
) -> pd.Series:
    """Vectorized sibling of classify_regime(): same thresholds, same
    TRENDING/RANGING/UNSTABLE/UNKNOWN labels, evaluated at every bar
    instead of only the latest one. Exists for the same research/
    diagnostic reason classify_volatility_series() does -- see its
    docstring. Not used by any live decision path."""
    adx_series = adx(bars["high"], bars["low"], bars["close"], adx_window)
    trending = adx_series >= trend_threshold

    # _atr_pct_series() dropna()s its atr_window warmup bars, so it's
    # shorter than bars.index/adx_series -- reindex back onto the full
    # index (NaN for the dropped bars) before combining with `trending`,
    # or the misaligned-shorter-index boolean mask raises.
    atr_pct = _atr_pct_series(bars, atr_window).reindex(bars.index)
    vol_median = atr_pct.rolling(volatility_lookback, min_periods=MIN_VOLATILITY_HISTORY).median()
    vol_ratio = atr_pct / vol_median
    unstable = (~trending) & vol_median.notna() & (vol_median > 0) & (vol_ratio >= unstable_volatility_ratio)

    result = pd.Series(UNKNOWN, index=bars.index)
    known = adx_series.notna()
    result.loc[known & trending] = TRENDING
    result.loc[known & ~trending] = RANGING
    result.loc[known & unstable] = UNSTABLE
    return result


def classify_regime(
    bars: pd.DataFrame,
    adx_window: int = 14,
    trend_threshold: float = 25.0,
    atr_window: int = 14,
    volatility_lookback: int = 100,
    unstable_volatility_ratio: float = 2.5,
) -> str:
    """Classifies the most recent bar's regime from the same raw OHLC
    history a strategy would see. Computed from raw bars, not a
    strategy's own prepared indicators, because regime classification has
    to happen *before* a strategy is even picked (trading.cfd.selector) --
    it can't depend on which one that turns out to be.

    unstable_volatility_ratio is deliberately a higher bar than
    classify_volatility()'s own high_ratio (2.5x vs 1.5x its recent
    median) -- UNSTABLE is meant to catch a genuine spike, not just
    "somewhat more active than usual," which alone doesn't disqualify a
    trend-following strategy already sizing its stop off ATR."""
    if len(bars) < adx_window + 1:
        return UNKNOWN
    adx_series = adx(bars["high"], bars["low"], bars["close"], adx_window)
    latest_adx = adx_series.iloc[-1]
    if pd.isna(latest_adx):
        return UNKNOWN
    trending = latest_adx >= trend_threshold

    if not trending:
        atr_pct = _atr_pct_series(bars, atr_window)
        if len(atr_pct) >= MIN_VOLATILITY_HISTORY:
            history = atr_pct.iloc[-volatility_lookback:]
            median = history.median()
            if median > 0 and history.iloc[-1] / median >= unstable_volatility_ratio:
                return UNSTABLE

    return TRENDING if trending else RANGING

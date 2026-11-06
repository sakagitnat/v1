"""Smoothed Equity / High-Water-Mark -- src/trading/cfd/smoothed_equity.py

Closes Revision 3 gap #5 (docs/ARCHITECTURE_AUDIT.md): trading.cfd.risk.
CfdRiskManager used to size every new position off raw, instantaneous
virtual equity -- so a quick gain (docs/VISION.md's own example: $100 ->
$120) would scale the very next trade's risk upward by the same
proportion immediately, with no confirmation that the gain reflects a
durable edge rather than short-term noise.

update_smoothed_equity() is a EMA (exponential moving average) that's
deliberately ASYMMETRIC: it damps how fast the equity basis used for
SIZING catches up to a GAIN, but never lags behind a LOSS -- capped at
`min(ema, current_equity)`, so on any drop it snaps immediately to the
new, lower current equity. docs/VISION.md only ever asks that recent
profit not be used as an excuse to scale risk up too fast; it never asks
protection to react slower after a loss, and trading.cfd.
drawdown_monitor (gap #4) already needs a fast, unlagged read of current
equity to work correctly. trading.cfd.scheduler feeds this smoothed
figure into CfdRiskManager's risk_per_trade_override mechanism for
SIZING ONLY -- every protective check (capital floor, daily-loss circuit
breaker, drawdown tiers) still uses raw, real-time equity.

update_high_water_mark() tracks the highest virtual equity ever
observed -- a ratchet, never decreases -- the reference point
trading.cfd.drawdown_monitor measures "how far below the best we've ever
done" against, which is what "drawdown" actually means (not "how far
below where we started").
"""
from typing import Optional


def update_smoothed_equity(previous_smoothed: Optional[float], current_equity: float, alpha: float) -> float:
    """previous_smoothed=None (no prior value -- e.g. the very first run)
    means "start exactly at current equity," not "start at zero and let
    the EMA slowly catch up," which would nonsensically undersize every
    trade until it converged. alpha in (0, 1]: how much of the gap to
    current equity closes each run on a gain -- 1.0 means no smoothing
    at all (matches raw equity immediately), smaller values smooth
    harder. Never returns a value above current_equity (see module
    docstring) -- a loss is reflected in sizing immediately, never
    lagged."""
    if previous_smoothed is None:
        return current_equity
    alpha = max(0.0, min(1.0, alpha))
    ema = previous_smoothed + alpha * (current_equity - previous_smoothed)
    return min(ema, current_equity)


def update_high_water_mark(previous_hwm: Optional[float], current_equity: float) -> float:
    """A ratchet -- never decreases. previous_hwm=None means this is the
    first observation, so it becomes the initial high-water-mark."""
    if previous_hwm is None:
        return current_equity
    return max(previous_hwm, current_equity)

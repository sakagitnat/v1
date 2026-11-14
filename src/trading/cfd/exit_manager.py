"""Adaptive Exit Management -- src/trading/cfd/exit_manager.py

Closes Revision 3 gap #1 (docs/ARCHITECTURE_AUDIT.md): every registered
strategy used to compute a fixed R-multiple take-profit and send it to
Deriv as a hard, whole-position limit order -- capping every winner at a
small fixed multiple, with no trailing stop, no partial close, and no
way for a genuinely big winner to run. Per docs/VISION.md's "Position
holding period and exit philosophy": initial risk and realized upside
are separate decisions, a uniform fixed take-profit is forbidden, and a
profitable position needs protection (trailing stop, adaptive exit, or
partial close) once meaningfully in profit -- just never a single fixed
number applied identically everywhere.

This module holds the pure exit math -- testable without a broker or an
event loop. trading.cfd.scheduler is what actually calls close_position()
when the trailing stop fires and what submits the split legs at entry.

Deriv Multipliers don't support a true partial sell of one contract
(unconfirmed anywhere in broker.py, and this project's stated discipline
is to never assume an unconfirmed API behavior against a live account) --
so "partial close" here means splitting one entry's already-computed
risk budget into two SEPARATE contracts at entry time, not selling part
of one:
  - a "scalp" leg: a fraction of the stake, with the strategy's own
    normal fixed target -- locks in some profit early, same as today's
    single-leg behavior but sized down.
  - a "runner" leg: the remaining stake, with no *effective* fixed
    target -- see runner_backstop_multiple below for why it still gets
    A take-profit value sent to Deriv, just a very wide one. Managed
    under normal conditions by the trailing stop (update_trailing_stop/
    trailing_stop_hit below) and the strategy's own signal exit, not by
    that backstop.

Both legs are tagged with the same thesis_key (see
trading.cfd.portfolio_risk) since splitting a position never turns one
opportunity into two independent ones -- their combined risk is checked
against every ceiling as a single unit before either is submitted.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class TrailingStopState:
    entry_price: float
    initial_stop_price: float
    side: str  # "long" or "short"
    activated: bool = False
    current_stop_price: Optional[float] = None
    """None until activated -- before that, the leg is protected only by
    Deriv's own initial stop_loss_amount (the order-time stop), exactly
    as every position was before this module existed."""

    def as_dict(self) -> dict:
        return {
            "entry_price": self.entry_price,
            "initial_stop_price": self.initial_stop_price,
            "side": self.side,
            "activated": self.activated,
            "current_stop_price": self.current_stop_price,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrailingStopState":
        return cls(
            entry_price=data["entry_price"],
            initial_stop_price=data["initial_stop_price"],
            side=data["side"],
            activated=data.get("activated", False),
            current_stop_price=data.get("current_stop_price"),
        )


def update_trailing_stop(
    state: TrailingStopState,
    current_price: float,
    current_atr: float,
    activation_r_multiple: float,
    trail_atr_multiple: float,
) -> TrailingStopState:
    """Returns a new TrailingStopState reflecting the latest bar -- never
    loosens an already-activated stop, only ratchets it toward locking in
    more profit (a ratchet, same "never give back protection already
    earned" shape as docs/VISION.md's high-water-mark guidance
    elsewhere). Activates once price has moved favorably by at least
    activation_r_multiple times the ORIGINAL stop distance (entry to the
    initial, Deriv-side stop) -- before that, unchanged from today:
    protected only by Deriv's own initial stop_loss_amount. current_atr
    is recomputed fresh each call from the latest candles, so the trail
    distance adapts to current volatility, not a value frozen at entry --
    the "regime-aware exit" docs/VISION.md asks for."""
    initial_stop_distance = abs(state.entry_price - state.initial_stop_price)
    if initial_stop_distance <= 0:
        return state

    favorable_move = (
        current_price - state.entry_price if state.side == "long" else state.entry_price - current_price
    )
    activated = state.activated or favorable_move >= activation_r_multiple * initial_stop_distance
    if not activated:
        return state

    trail_distance = trail_atr_multiple * current_atr
    if state.side == "long":
        candidate_stop = current_price - trail_distance
        new_stop = max(candidate_stop, state.current_stop_price or state.initial_stop_price)
    else:
        candidate_stop = current_price + trail_distance
        new_stop = min(candidate_stop, state.current_stop_price or state.initial_stop_price)

    return TrailingStopState(
        entry_price=state.entry_price,
        initial_stop_price=state.initial_stop_price,
        side=state.side,
        activated=True,
        current_stop_price=new_stop,
    )


def trailing_stop_hit(state: TrailingStopState, bar_low: float, bar_high: float) -> bool:
    """True if the latest bar's range crossed the CURRENT trailing stop.
    Only meaningful once activated (current_stop_price is set) -- before
    that this always returns False, since Deriv's own initial
    stop_loss_amount is the only protection in force and the scheduler
    must not duplicate that check here."""
    if not state.activated or state.current_stop_price is None:
        return False
    if state.side == "long":
        return bar_low <= state.current_stop_price
    return bar_high >= state.current_stop_price


def split_stake_for_partial_close(
    stake: float,
    risk_amount: float,
    take_profit_amount: float,
    partial_close_fraction: float,
    min_stake: float,
    runner_backstop_multiple: float = 10.0,
) -> Optional[tuple[dict, dict]]:
    """Splits one entry's already risk-budgeted (stake, risk_amount,
    take_profit_amount) into a "scalp" leg (partial_close_fraction of
    the total, keeping the strategy's own normal target) and a "runner"
    leg (the remainder). Returns None if either leg's stake would fall
    below min_stake -- the caller should then open a single
    runner-only leg with the FULL stake instead of forcing an invalid
    sub-minimum order just to force a split.

    The runner leg's take_profit_amount is NOT omitted -- Deriv's
    proposal request accepting a limit_order with no take_profit at all
    hasn't been confirmed live against this project's API flow (see
    broker.py's "confirm against a live response, don't assume"
    discipline), so instead it's set runner_backstop_multiple times
    wider than its own proportional target: present, but a rare
    catastrophic backstop, never the leg's real exit mechanism -- that's
    the trailing stop and the strategy's own signal exit, both handled
    in trading.cfd.scheduler."""
    scalp_stake = round(stake * partial_close_fraction, 2)
    runner_stake = round(stake - scalp_stake, 2)
    if scalp_stake < min_stake or runner_stake < min_stake:
        return None

    scalp_risk = round(risk_amount * partial_close_fraction, 2)
    runner_risk = round(risk_amount - scalp_risk, 2)
    scalp_tp = round(take_profit_amount * partial_close_fraction, 2)
    runner_proportional_tp = take_profit_amount - scalp_tp
    runner_tp = round(runner_proportional_tp * runner_backstop_multiple, 2)

    scalp = {"stake": scalp_stake, "risk_amount": scalp_risk, "take_profit_amount": scalp_tp}
    runner = {"stake": runner_stake, "risk_amount": runner_risk, "take_profit_amount": runner_tp}
    return scalp, runner

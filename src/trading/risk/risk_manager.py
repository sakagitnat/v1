from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RiskManager:
    equity: float
    risk_per_trade: float = 0.01
    max_open_positions: int = 5
    max_daily_loss_pct: float = 0.03
    capital_floor: Optional[float] = None
    """Once equity drops to or below this, new positions stop opening until
    it recovers above it. Unlike the daily circuit breaker, this never
    resets on its own -- it's meant to protect the original principal, not
    just cap one bad day. Not an absolute guarantee: an overnight gap past
    a stop-loss can still land below it in one move."""
    ladder: bool = False
    """If True (and capital_floor is set), scale risk_per_trade by how far
    equity has grown above the floor -- smaller risk while the cushion
    above the floor is thin, standard risk in the middle, larger risk once
    there's a healthy profit cushion to risk instead of the original
    principal ("trading with house money")."""

    _daily_start_equity: float = field(init=False, repr=False)
    _open_positions: int = field(init=False, default=0, repr=False)
    _halted: bool = field(init=False, default=False, repr=False)

    def __post_init__(self):
        self._daily_start_equity = self.equity

    def effective_risk_per_trade(self) -> float:
        if not self.ladder or not self.capital_floor or self.capital_floor <= 0:
            return self.risk_per_trade
        cushion_pct = (self.equity - self.capital_floor) / self.capital_floor
        if cushion_pct < 0.20:
            return self.risk_per_trade * 0.5
        if cushion_pct < 0.50:
            return self.risk_per_trade
        return self.risk_per_trade * 1.5

    def at_or_below_floor(self) -> bool:
        return self.capital_floor is not None and self.equity <= self.capital_floor

    def position_size(self, entry_price: float, stop_price: Optional[float]) -> int:
        if self._halted or self._open_positions >= self.max_open_positions or entry_price <= 0:
            return 0
        if self.at_or_below_floor():
            return 0

        if stop_price is None:
            # No stop-loss defined (e.g. a buy-and-hold strategy) -- size as
            # an equal-weight slice of equity instead of a risk-based amount.
            allocation = self.equity / self.max_open_positions
            return max(0, int(allocation // entry_price))

        per_share_risk = entry_price - stop_price
        if per_share_risk <= 0:
            return 0
        risk_amount = self.equity * self.effective_risk_per_trade()
        shares_by_risk = int(risk_amount // per_share_risk)
        shares_affordable = int(self.equity // entry_price)
        return max(0, min(shares_by_risk, shares_affordable))

    def register_open(self):
        self._open_positions += 1

    def register_close(self, pnl: float):
        self._open_positions = max(0, self._open_positions - 1)
        self.equity += pnl
        if self._daily_start_equity > 0:
            daily_loss_pct = (self._daily_start_equity - self.equity) / self._daily_start_equity
            if daily_loss_pct >= self.max_daily_loss_pct:
                self._halted = True

    def reset_day(self):
        self._daily_start_equity = self.equity
        self._halted = False

    @property
    def halted(self) -> bool:
        return self._halted

    @property
    def open_positions(self) -> int:
        return self._open_positions

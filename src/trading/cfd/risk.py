from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CfdRiskManager:
    """Position sizing and circuit breakers for CFD/forex trading, in units
    rather than shares/dollars (OANDA orders are sized in instrument units,
    e.g. 1000 units of EUR_USD).

    Mirrors trading/risk/risk_manager.py's protective philosophy, with one
    fix already applied up front instead of re-discovered the hard way: the
    capital floor uses a strict "<", not "<=" -- otherwise setting the floor
    equal to the starting balance (the normal first move) would deadlock
    the account forever, since equity could never rise above a floor it's
    never allowed to trade away from. See risk_manager.py's docstring for
    the full story of that bug in the stock system.
    """

    equity: float
    risk_per_trade: float = 0.01
    max_open_positions: int = 3
    max_daily_loss_pct: float = 0.03
    capital_floor: Optional[float] = None

    _daily_start_equity: float = field(init=False, repr=False)
    _open_positions: int = field(init=False, default=0, repr=False)
    _halted: bool = field(init=False, default=False, repr=False)

    def __post_init__(self):
        self._daily_start_equity = self.equity

    def below_floor(self) -> bool:
        return self.capital_floor is not None and self.equity < self.capital_floor

    def _can_open_new_position(self) -> bool:
        return not (self._halted or self._open_positions >= self.max_open_positions or self.below_floor())

    def position_units(self, entry_price: float, stop_loss_price: float) -> int:
        """Whole units sized so a stop-out loses about risk_per_trade of
        equity. Positive entry_price/stop distance assumed for a long;
        callers going short should pass the same (positive) distance and
        negate the returned unit count themselves."""
        if not self._can_open_new_position() or entry_price <= 0:
            return 0
        per_unit_risk = abs(entry_price - stop_loss_price)
        if per_unit_risk <= 0:
            return 0
        risk_amount = self.equity * self.risk_per_trade
        return max(0, int(risk_amount // per_unit_risk))

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

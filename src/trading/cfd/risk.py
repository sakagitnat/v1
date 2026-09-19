from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CfdRiskManager:
    """Position sizing and circuit breakers for Deriv Multipliers trading.

    Deriv's multiplier contracts are sized by a dollar "stake" plus a
    leverage "multiplier", not by instrument units the way OANDA/most CFD
    brokers work -- and stop_loss/take_profit on Deriv are dollar P&L
    amounts, not price levels (see broker.py's submit_multiplier_order).
    stake_and_limits() converts the strategy's ATR-based price-distance
    stop/target into the (stake, stop_loss_amount, take_profit_amount)
    Deriv's API actually wants, sized so a stop-out loses about
    risk_per_trade of equity regardless of the instrument's price scale.

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
    multiplier: int = 20
    """Deriv's leverage factor applied to the stake. Higher means a
    smaller stake reaches the same risk_amount stop-loss, i.e. less cash
    tied up per trade for the same dollar risk -- but Deriv caps which
    multipliers are offered per instrument, so this needs to match
    whatever's actually available once that's checked against the API."""

    _daily_start_equity: float = field(init=False, repr=False)
    _open_positions: int = field(init=False, default=0, repr=False)
    _halted: bool = field(init=False, default=False, repr=False)

    def __post_init__(self):
        self._daily_start_equity = self.equity

    def below_floor(self) -> bool:
        return self.capital_floor is not None and self.equity < self.capital_floor

    def _can_open_new_position(self) -> bool:
        return not (self._halted or self._open_positions >= self.max_open_positions or self.below_floor())

    def stake_and_limits(
        self, entry_price: float, stop_price: float, take_profit_price: float
    ) -> tuple[float, float, float]:
        """Returns (stake, stop_loss_amount, take_profit_amount), all in
        account currency, sized so a stop-out loses about risk_per_trade of
        equity. Returns (0.0, 0.0, 0.0) if a new position can't open right
        now (floor breached, daily loss halt, or max positions reached) or
        the inputs are degenerate (zero stop distance)."""
        if not self._can_open_new_position() or entry_price <= 0:
            return 0.0, 0.0, 0.0
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return 0.0, 0.0, 0.0
        target_distance = abs(take_profit_price - entry_price)

        risk_amount = self.equity * self.risk_per_trade
        stake = min(risk_amount * entry_price / (self.multiplier * stop_distance), self.equity)
        take_profit_amount = risk_amount * (target_distance / stop_distance)
        return round(stake, 2), round(risk_amount, 2), round(take_profit_amount, 2)

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

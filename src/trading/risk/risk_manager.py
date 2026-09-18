from dataclasses import dataclass, field


@dataclass
class RiskManager:
    equity: float
    risk_per_trade: float = 0.01
    max_open_positions: int = 5
    max_daily_loss_pct: float = 0.03

    _daily_start_equity: float = field(init=False, repr=False)
    _open_positions: int = field(init=False, default=0, repr=False)
    _halted: bool = field(init=False, default=False, repr=False)

    def __post_init__(self):
        self._daily_start_equity = self.equity

    def position_size(self, entry_price: float, stop_price: float) -> int:
        if self._halted or self._open_positions >= self.max_open_positions:
            return 0
        per_share_risk = entry_price - stop_price
        if per_share_risk <= 0 or entry_price <= 0:
            return 0
        risk_amount = self.equity * self.risk_per_trade
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

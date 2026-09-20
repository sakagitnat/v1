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
    min_stake: float = 1.0
    """Deriv's confirmed live minimum stake for a Multipliers order. A
    risk-budgeted stake smaller than this can't be placed as-is -- see
    stake_and_limits()'s docstring for why the fix is SKIP TRADE, not
    rounding the stake up to this floor."""
    """Deriv's leverage factor applied to the stake. Higher means a
    smaller stake reaches the same risk_amount stop-loss, i.e. less cash
    tied up per trade for the same dollar risk -- but Deriv caps which
    multipliers are offered per instrument, so this needs to match
    whatever's actually available once that's checked against the API."""
    daily_start_equity: Optional[float] = None
    """Equity at the start of today's UTC calendar day, for the
    daily-loss circuit breaker. Defaults to `equity` (treats this as a
    fresh day) if not given -- but a caller running across multiple
    processes in the same real day (trading.cfd.scheduler, via
    trading.cfd.state.get_daily_risk_tracking/set_daily_risk_tracking)
    should pass yesterday's-run value in, and persist this attribute's
    value back out after, or the breaker only ever sees whatever loss
    happened to occur within one single run -- never a full day's worth."""
    initially_halted: bool = False
    """Whether today's daily-loss threshold was already breached in an
    earlier run today -- persisted the same way as daily_start_equity."""
    stake_safety_margin: float = 1.0
    """Closes Revision 3 gap #7 (docs/ARCHITECTURE_AUDIT.md): "risk 1%"
    means the estimated max loss of one position, with headroom left for
    execution reality -- not a number that assumes a perfect fill. A
    strategy's signal computes stop/target off a candle's CLOSE price,
    but the actual Deriv proposal/buy executes at whatever price is
    quoted a moment later -- usually close, never guaranteed identical.
    1.0 (the default) applies no margin, matching every existing test
    and backtest run unchanged; a caller can pass e.g. 0.95 to size to
    95% of the theoretical risk-budgeted stake, leaving 5% headroom so a
    small unfavorable difference between the signal's price and the
    actual fill doesn't push the realized risk over what was budgeted.
    Deriv's own stop-loss/take-profit fills themselves are a separate,
    already-guaranteed-exact matter (see broker.py's docstring) -- this
    margin is about the ENTRY fill, not those."""

    _open_positions: int = field(init=False, default=0, repr=False)
    _halted: bool = field(init=False, repr=False)

    def __post_init__(self):
        if self.daily_start_equity is None:
            self.daily_start_equity = self.equity
        self._halted = self.initially_halted

    def below_floor(self) -> bool:
        return self.capital_floor is not None and self.equity < self.capital_floor

    def _can_open_new_position(self) -> bool:
        return not (self._halted or self._open_positions >= self.max_open_positions or self.below_floor())

    def stake_and_limits(
        self,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
        risk_per_trade_override: Optional[float] = None,
    ) -> tuple[float, float, float]:
        """Returns (stake, stop_loss_amount, take_profit_amount), all in
        account currency, sized so a stop-out loses about risk_per_trade of
        equity. Returns (0.0, 0.0, 0.0) if a new position can't open right
        now (floor breached, daily loss halt, or max positions reached) or
        the inputs are degenerate (zero stop distance).

        risk_per_trade_override, if given, is used instead of the
        constructor's risk_per_trade for this one call -- how
        trading.cfd.portfolio_allocator's per-strategy weighting actually
        takes effect (a lower-conviction ACTIVE strategy sharing a regime
        with others gets a smaller slice of the configured risk budget).
        Clamped to never exceed risk_per_trade regardless of what's passed
        in: allocation can only ever shrink a trade's risk relative to what
        a human already configured, never raise it above that ceiling --
        docs/VISION.md's "Autonomy boundaries" forbids the AI increasing
        risk on its own initiative, so that boundary is enforced right
        here, not just trusted of the caller.

        Note: when stop_distance exceeds entry_price / multiplier, stake
        comes out smaller than stop_loss_amount (risk_amount) -- Deriv's
        capped-loss guarantee means the real max loss on that trade is the
        stake, not the fuller risk_amount sent as stop_loss. Confirmed by
        cfd/backtest.py's simulation: the price move needed to reach
        stop_loss_amount in dollar P&L lands exactly at stop_price by
        construction, but if that dollar amount is larger than the stake
        itself, Deriv's contract-level cap binds first. Harmless (the
        trade still loses less than intended, never more) but means the
        effective risk_per_trade can come in under budget for wide
        stops/low multipliers -- worth knowing when reading backtest
        results, not something to "fix" here.

        Also returns (0.0, 0.0, 0.0) -- SKIP TRADE -- when the
        risk-budgeted stake comes out below min_stake. Deriv won't accept
        an order smaller than min_stake, and forcing the stake UP to that
        floor would risk more of equity than risk_per_trade allows, most
        acutely on a small (e.g. $100) account where min_stake is a much
        larger fraction of equity than on a $10,000 one. Per
        docs/VISION.md's capital-model rule: never round a position size
        up past the configured risk -- skip the trade instead."""
        if not self._can_open_new_position() or entry_price <= 0:
            return 0.0, 0.0, 0.0
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return 0.0, 0.0, 0.0
        target_distance = abs(take_profit_price - entry_price)

        risk_per_trade = self.risk_per_trade
        if risk_per_trade_override is not None:
            risk_per_trade = max(0.0, min(risk_per_trade, risk_per_trade_override))
        risk_amount = self.equity * risk_per_trade * self.stake_safety_margin
        stake = min(risk_amount * entry_price / (self.multiplier * stop_distance), self.equity)
        if stake < self.min_stake:
            return 0.0, 0.0, 0.0
        take_profit_amount = risk_amount * (target_distance / stop_distance)
        return round(stake, 2), round(risk_amount, 2), round(take_profit_amount, 2)

    def register_open(self):
        self._open_positions += 1

    def register_close(self, pnl: float):
        self._open_positions = max(0, self._open_positions - 1)
        self.equity += pnl
        if self.daily_start_equity > 0:
            daily_loss_pct = (self.daily_start_equity - self.equity) / self.daily_start_equity
            if daily_loss_pct >= self.max_daily_loss_pct:
                self._halted = True

    def reset_day(self):
        self.daily_start_equity = self.equity
        self._halted = False

    @property
    def halted(self) -> bool:
        return self._halted

    @property
    def open_positions(self) -> int:
        return self._open_positions

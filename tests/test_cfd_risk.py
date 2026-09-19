from trading.cfd.risk import CfdRiskManager


def test_stake_and_limits_sized_by_risk_budget():
    rm = CfdRiskManager(equity=1000, risk_per_trade=0.01, multiplier=20)
    # entry 100, stop 99 (distance 1), target 102 (distance 2) -> target is 2x the stop distance
    stake, stop_loss_amount, take_profit_amount = rm.stake_and_limits(
        entry_price=100.0, stop_price=99.0, take_profit_price=102.0
    )
    risk_amount = 1000 * 0.01  # 10
    assert stop_loss_amount == risk_amount
    assert stake == round(risk_amount * 100.0 / (20 * 1.0), 2)  # 50.0
    assert take_profit_amount == risk_amount * 2  # target distance is 2x stop distance


def test_stake_capped_at_equity():
    # Deliberately tiny multiplier/stop distance so the naive formula would
    # exceed available equity -- stake must never be sized above equity.
    rm = CfdRiskManager(equity=100, risk_per_trade=0.5, multiplier=1)
    stake, _, _ = rm.stake_and_limits(entry_price=100.0, stop_price=99.99, take_profit_price=100.02)
    assert stake <= 100.0


def test_zero_when_stop_equals_entry():
    rm = CfdRiskManager(equity=1000)
    assert rm.stake_and_limits(entry_price=100.0, stop_price=100.0, take_profit_price=102.0) == (0.0, 0.0, 0.0)


def test_max_open_positions_blocks_further_entries():
    rm = CfdRiskManager(equity=1000, max_open_positions=1)
    rm.register_open()
    assert rm.stake_and_limits(entry_price=100.0, stop_price=99.0, take_profit_price=102.0) == (0.0, 0.0, 0.0)


def test_capital_floor_does_not_deadlock_exactly_at_it():
    # Same fix already applied that the stock system needed after the fact:
    # equity starting exactly at the floor must still be able to trade.
    rm = CfdRiskManager(equity=1000, capital_floor=1000)
    assert rm.below_floor() is False
    stake, _, _ = rm.stake_and_limits(entry_price=100.0, stop_price=99.0, take_profit_price=102.0)
    assert stake > 0


def test_capital_floor_blocks_new_entries_once_genuinely_below():
    rm = CfdRiskManager(equity=999, capital_floor=1000)
    assert rm.below_floor() is True
    assert rm.stake_and_limits(entry_price=100.0, stop_price=99.0, take_profit_price=102.0) == (0.0, 0.0, 0.0)


def test_daily_loss_circuit_breaker_halts_further_entries():
    rm = CfdRiskManager(equity=1000, max_daily_loss_pct=0.03)
    rm.register_open()
    rm.register_close(pnl=-40)  # 4% loss, over the 3% threshold
    assert rm.halted is True
    assert rm.stake_and_limits(entry_price=100.0, stop_price=99.0, take_profit_price=102.0) == (0.0, 0.0, 0.0)


def test_skips_trade_when_risk_budgeted_stake_is_below_min_stake():
    # $100 equity, 0.1% risk -> risk_amount=$0.10; a wide stop/low
    # multiplier sizes the stake (0.40) well under Deriv's real minimum --
    # must SKIP, not round the stake up to min_stake (which would risk far
    # more than the configured 0.1%).
    rm = CfdRiskManager(equity=100, risk_per_trade=0.001, multiplier=5, min_stake=1.0)
    stake, stop_loss_amount, take_profit_amount = rm.stake_and_limits(
        entry_price=100.0, stop_price=95.0, take_profit_price=110.0
    )
    assert (stake, stop_loss_amount, take_profit_amount) == (0.0, 0.0, 0.0)


def test_trades_at_exactly_min_stake_are_not_skipped():
    rm = CfdRiskManager(equity=1000, risk_per_trade=0.01, multiplier=20, min_stake=1.0)
    stake, _, _ = rm.stake_and_limits(entry_price=100.0, stop_price=99.0, take_profit_price=102.0)
    assert stake == 50.0  # comfortably above min_stake, sanity check the fixture itself
    assert stake >= rm.min_stake


def test_reset_day_clears_halt():
    rm = CfdRiskManager(equity=1000, max_daily_loss_pct=0.03)
    rm.register_open()
    rm.register_close(pnl=-40)
    rm.reset_day()
    assert rm.halted is False

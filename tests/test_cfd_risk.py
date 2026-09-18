from trading.cfd.risk import CfdRiskManager


def test_position_units_sized_by_risk_budget():
    rm = CfdRiskManager(equity=1000, risk_per_trade=0.01)
    units = rm.position_units(entry_price=1.1000, stop_loss_price=1.0950)  # 0.005 per-unit risk
    assert units == int(10.0 // 0.005)  # risk_amount 10 / per_unit_risk 0.005


def test_position_units_zero_when_stop_equals_entry():
    rm = CfdRiskManager(equity=1000, risk_per_trade=0.01)
    assert rm.position_units(entry_price=1.1000, stop_loss_price=1.1000) == 0


def test_max_open_positions_blocks_further_entries():
    rm = CfdRiskManager(equity=1000, max_open_positions=1)
    rm.register_open()
    assert rm.position_units(entry_price=1.1, stop_loss_price=1.09) == 0


def test_capital_floor_does_not_deadlock_exactly_at_it():
    # Same fix already applied that the stock system needed after the fact:
    # equity starting exactly at the floor must still be able to trade.
    rm = CfdRiskManager(equity=1000, capital_floor=1000)
    assert rm.below_floor() is False
    assert rm.position_units(entry_price=1.1, stop_loss_price=1.09) > 0


def test_capital_floor_blocks_new_entries_once_genuinely_below():
    rm = CfdRiskManager(equity=999, capital_floor=1000)
    assert rm.below_floor() is True
    assert rm.position_units(entry_price=1.1, stop_loss_price=1.09) == 0


def test_daily_loss_circuit_breaker_halts_further_entries():
    rm = CfdRiskManager(equity=1000, max_daily_loss_pct=0.03)
    rm.register_open()
    rm.register_close(pnl=-40)  # 4% loss, over the 3% threshold
    assert rm.halted is True
    assert rm.position_units(entry_price=1.1, stop_loss_price=1.09) == 0


def test_reset_day_clears_halt():
    rm = CfdRiskManager(equity=1000, max_daily_loss_pct=0.03)
    rm.register_open()
    rm.register_close(pnl=-40)
    rm.reset_day()
    assert rm.halted is False

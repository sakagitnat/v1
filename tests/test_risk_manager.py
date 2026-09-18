from trading.risk.risk_manager import RiskManager


def test_position_size_respects_risk_budget():
    rm = RiskManager(equity=100_000, risk_per_trade=0.01)
    shares = rm.position_size(entry_price=100, stop_price=95)
    assert shares == 200  # risk budget 1000 / per-share risk 5


def test_position_size_zero_when_stop_above_entry():
    rm = RiskManager(equity=100_000, risk_per_trade=0.01)
    assert rm.position_size(entry_price=100, stop_price=105) == 0


def test_daily_loss_halts_new_trades():
    rm = RiskManager(equity=100_000, risk_per_trade=0.01, max_daily_loss_pct=0.02)
    rm.register_open()
    rm.register_close(pnl=-2500)  # -2.5% loss, over the 2% cap
    assert rm.halted is True
    assert rm.position_size(entry_price=100, stop_price=95) == 0


def test_reset_day_clears_halt():
    rm = RiskManager(equity=100_000, risk_per_trade=0.01, max_daily_loss_pct=0.02)
    rm.register_open()
    rm.register_close(pnl=-2500)
    assert rm.halted is True
    rm.reset_day()
    assert rm.halted is False


def test_max_open_positions_enforced():
    rm = RiskManager(equity=100_000, risk_per_trade=0.5, max_open_positions=1)
    rm.register_open()
    assert rm.position_size(entry_price=100, stop_price=95) == 0


def test_position_size_with_no_stop_uses_equal_weight_allocation():
    rm = RiskManager(equity=100_000, max_open_positions=5)
    shares = rm.position_size(entry_price=100, stop_price=None)
    assert shares == 200  # (100,000 / 5 slots) / 100 per share


def test_position_size_with_no_stop_still_respects_max_positions():
    rm = RiskManager(equity=100_000, max_open_positions=1)
    rm.register_open()
    assert rm.position_size(entry_price=100, stop_price=None) == 0

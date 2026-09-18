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


def test_capital_floor_blocks_new_entries_at_or_below_it():
    rm = RiskManager(equity=100, risk_per_trade=0.01, capital_floor=100)
    assert rm.at_or_below_floor() is True
    assert rm.position_size(entry_price=10, stop_price=9) == 0


def test_capital_floor_does_not_block_above_it():
    rm = RiskManager(equity=101, risk_per_trade=0.01, capital_floor=100)
    assert rm.at_or_below_floor() is False


def test_ladder_reduces_risk_with_thin_cushion():
    rm = RiskManager(equity=110, risk_per_trade=0.02, capital_floor=100, ladder=True)  # 10% cushion
    assert rm.effective_risk_per_trade() == 0.01  # halved


def test_ladder_keeps_base_risk_with_moderate_cushion():
    rm = RiskManager(equity=130, risk_per_trade=0.02, capital_floor=100, ladder=True)  # 30% cushion
    assert rm.effective_risk_per_trade() == 0.02


def test_ladder_increases_risk_with_large_cushion():
    rm = RiskManager(equity=160, risk_per_trade=0.02, capital_floor=100, ladder=True)  # 60% cushion
    assert rm.effective_risk_per_trade() == 0.03  # 1.5x


def test_ladder_has_no_effect_when_disabled():
    rm = RiskManager(equity=160, risk_per_trade=0.02, capital_floor=100, ladder=False)
    assert rm.effective_risk_per_trade() == 0.02


def test_ladder_has_no_effect_without_a_floor():
    rm = RiskManager(equity=160, risk_per_trade=0.02, ladder=True)
    assert rm.effective_risk_per_trade() == 0.02

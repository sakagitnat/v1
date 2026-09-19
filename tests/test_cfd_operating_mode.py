import pytest

from trading.cfd.operating_mode import (
    AGGRESSIVE,
    DEFENSIVE,
    NORMAL,
    RECOVERY,
    effective_max_open_positions,
    effective_risk_per_trade,
)


def test_normal_mode_is_unchanged():
    assert effective_risk_per_trade(NORMAL, base_risk_per_trade=0.01) == 0.01
    assert effective_max_open_positions(NORMAL, base_max_open_positions=3) == 3


def test_defensive_and_recovery_use_the_same_conservative_multiplier():
    defensive = effective_risk_per_trade(DEFENSIVE, base_risk_per_trade=0.01)
    recovery = effective_risk_per_trade(RECOVERY, base_risk_per_trade=0.01)
    assert defensive == recovery == 0.005


def test_aggressive_scales_up_but_never_past_the_absolute_ceiling(monkeypatch):
    from trading.cfd import operating_mode as om

    monkeypatch.setattr(om.settings, "cfd_max_risk_per_trade_ceiling", 0.03)
    # 0.01 * 1.5 = 0.015, under the 0.03 ceiling -- unaffected
    assert effective_risk_per_trade(AGGRESSIVE, base_risk_per_trade=0.01) == 0.015
    # 0.05 * 1.5 = 0.075, past the ceiling -- clamped to 0.03
    assert effective_risk_per_trade(AGGRESSIVE, base_risk_per_trade=0.05) == 0.03


def test_defensive_and_recovery_reduce_max_open_positions():
    assert effective_max_open_positions(DEFENSIVE, base_max_open_positions=4) == 2
    assert effective_max_open_positions(RECOVERY, base_max_open_positions=4) == 2


def test_max_open_positions_never_falls_below_one():
    assert effective_max_open_positions(DEFENSIVE, base_max_open_positions=1) == 1


def test_aggressive_does_not_raise_max_open_positions():
    # risk_per_trade already scales up in aggressive mode -- don't also
    # compound it with more concurrent exposure.
    assert effective_max_open_positions(AGGRESSIVE, base_max_open_positions=3) == 3


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        effective_risk_per_trade("yolo", base_risk_per_trade=0.01)
    with pytest.raises(ValueError):
        effective_max_open_positions("yolo", base_max_open_positions=3)

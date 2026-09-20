from trading.cfd.drawdown_monitor import (
    DEEP,
    MODERATE,
    NORMAL,
    SEVERE,
    DrawdownThresholds,
    classify_drawdown_tier,
    drawdown_risk_multiplier,
)


def _thresholds(moderate=0.10, deep=0.20, severe=0.30, moderate_mult=0.75, deep_mult=0.5):
    return DrawdownThresholds(
        moderate_pct=moderate, deep_pct=deep, severe_pct=severe,
        moderate_multiplier=moderate_mult, deep_multiplier=deep_mult,
    )


def test_no_drawdown_is_normal():
    assert classify_drawdown_tier(100.0, 100.0, _thresholds()) == NORMAL


def test_zero_or_negative_high_water_mark_is_normal():
    assert classify_drawdown_tier(50.0, 0.0, _thresholds()) == NORMAL


def test_just_under_moderate_threshold_is_still_normal():
    # 9% drawdown, moderate threshold is 10%
    assert classify_drawdown_tier(91.0, 100.0, _thresholds()) == NORMAL


def test_at_moderate_threshold_is_moderate():
    assert classify_drawdown_tier(90.0, 100.0, _thresholds()) == MODERATE


def test_at_deep_threshold_is_deep():
    assert classify_drawdown_tier(80.0, 100.0, _thresholds()) == DEEP


def test_at_severe_threshold_is_severe():
    assert classify_drawdown_tier(70.0, 100.0, _thresholds()) == SEVERE


def test_beyond_severe_is_still_severe():
    assert classify_drawdown_tier(40.0, 100.0, _thresholds()) == SEVERE


def test_equity_above_high_water_mark_is_normal_not_negative_drawdown():
    # Equity can exceed the recorded HWM only transiently (e.g. HWM not
    # yet updated this run) -- must never read as a negative drawdown.
    assert classify_drawdown_tier(110.0, 100.0, _thresholds()) == NORMAL


def test_multiplier_for_each_tier():
    t = _thresholds()
    assert drawdown_risk_multiplier(NORMAL, t) == 1.0
    assert drawdown_risk_multiplier(MODERATE, t) == 0.75
    assert drawdown_risk_multiplier(DEEP, t) == 0.5
    assert drawdown_risk_multiplier(SEVERE, t) == 0.0

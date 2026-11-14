from trading.cfd.smoothed_equity import update_high_water_mark, update_smoothed_equity


def test_smoothed_equity_starts_exactly_at_current_equity_when_no_prior_value():
    assert update_smoothed_equity(None, 100.0, alpha=0.3) == 100.0


def test_smoothed_equity_lags_behind_a_quick_gain():
    result = update_smoothed_equity(previous_smoothed=100.0, current_equity=120.0, alpha=0.3)
    assert 100.0 < result < 120.0
    assert result == 100.0 + 0.3 * (120.0 - 100.0)


def test_smoothed_equity_never_exceeds_current_equity():
    # Repeated gains -- smoothed should approach but never reach current
    # equity in one step, and must never overshoot it.
    smoothed = 100.0
    for current in [110.0, 120.0, 130.0]:
        smoothed = update_smoothed_equity(smoothed, current, alpha=0.5)
        assert smoothed <= current


def test_smoothed_equity_snaps_immediately_to_a_loss_no_lag():
    # Smoothed was tracking a prior gain (110, lagging behind a real 120)
    # -- a sudden drop to 90 must be reflected immediately, not lagged.
    result = update_smoothed_equity(previous_smoothed=110.0, current_equity=90.0, alpha=0.3)
    assert result == 90.0


def test_smoothed_equity_alpha_one_means_no_smoothing():
    result = update_smoothed_equity(previous_smoothed=100.0, current_equity=120.0, alpha=1.0)
    assert result == 120.0


def test_smoothed_equity_alpha_is_clamped_to_valid_range():
    over = update_smoothed_equity(previous_smoothed=100.0, current_equity=120.0, alpha=5.0)
    under = update_smoothed_equity(previous_smoothed=100.0, current_equity=120.0, alpha=-5.0)
    assert over == 120.0  # clamped to 1.0 -- full jump
    assert under == 100.0  # clamped to 0.0 -- no movement


def test_high_water_mark_starts_at_first_observation():
    assert update_high_water_mark(None, 100.0) == 100.0


def test_high_water_mark_ratchets_up_on_a_new_high():
    assert update_high_water_mark(100.0, 120.0) == 120.0


def test_high_water_mark_never_decreases():
    assert update_high_water_mark(120.0, 90.0) == 120.0

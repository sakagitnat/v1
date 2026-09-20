from trading.cfd.exit_manager import (
    TrailingStopState,
    split_stake_for_partial_close,
    trailing_stop_hit,
    update_trailing_stop,
)


def _state(side="long", entry=100.0, initial_stop=95.0, activated=False, current_stop=None):
    return TrailingStopState(
        entry_price=entry, initial_stop_price=initial_stop, side=side,
        activated=activated, current_stop_price=current_stop,
    )


def test_state_round_trips_through_dict():
    state = _state(activated=True, current_stop=98.0)
    restored = TrailingStopState.from_dict(state.as_dict())
    assert restored == state


def test_from_dict_defaults_missing_activation_fields():
    restored = TrailingStopState.from_dict({"entry_price": 100.0, "initial_stop_price": 95.0, "side": "long"})
    assert restored.activated is False
    assert restored.current_stop_price is None


def test_does_not_activate_before_reaching_the_activation_multiple():
    # stop distance = 5, activation_r_multiple=1.0 -> needs a 5-point
    # favorable move; only 3 points in so far.
    state = _state()
    updated = update_trailing_stop(state, current_price=103.0, current_atr=1.0, activation_r_multiple=1.0, trail_atr_multiple=2.0)
    assert updated.activated is False
    assert updated.current_stop_price is None


def test_activates_once_the_r_multiple_is_reached_long():
    state = _state()
    updated = update_trailing_stop(state, current_price=105.0, current_atr=1.0, activation_r_multiple=1.0, trail_atr_multiple=2.0)
    assert updated.activated is True
    assert updated.current_stop_price == 105.0 - 2.0 * 1.0  # 103.0


def test_activates_once_the_r_multiple_is_reached_short():
    state = _state(side="short", entry=100.0, initial_stop=105.0)
    updated = update_trailing_stop(state, current_price=95.0, current_atr=1.0, activation_r_multiple=1.0, trail_atr_multiple=2.0)
    assert updated.activated is True
    assert updated.current_stop_price == 95.0 + 2.0 * 1.0  # 97.0


def test_trailing_stop_only_ever_tightens_long():
    state = _state(activated=True, current_stop=103.0)
    # price pulls back slightly -- new candidate stop (108-2=106) is
    # still an improvement over 103, so it should ratchet up.
    improved = update_trailing_stop(state, current_price=108.0, current_atr=1.0, activation_r_multiple=1.0, trail_atr_multiple=2.0)
    assert improved.current_stop_price == 106.0

    # now price drops back toward entry -- candidate stop (100.5-2=98.5)
    # is WORSE than the already-locked-in 106, must never loosen.
    worsened = update_trailing_stop(improved, current_price=100.5, current_atr=1.0, activation_r_multiple=1.0, trail_atr_multiple=2.0)
    assert worsened.current_stop_price == 106.0


def test_trailing_stop_only_ever_tightens_short():
    state = _state(side="short", entry=100.0, initial_stop=105.0, activated=True, current_stop=97.0)
    improved = update_trailing_stop(state, current_price=92.0, current_atr=1.0, activation_r_multiple=1.0, trail_atr_multiple=2.0)
    assert improved.current_stop_price == 94.0  # 92 + 2

    worsened = update_trailing_stop(improved, current_price=99.0, current_atr=1.0, activation_r_multiple=1.0, trail_atr_multiple=2.0)
    assert worsened.current_stop_price == 94.0  # unchanged, would-be 101 is worse


def test_trail_distance_adapts_to_current_atr_not_a_frozen_value():
    state = _state(activated=True, current_stop=103.0)
    wider_vol = update_trailing_stop(state, current_price=110.0, current_atr=3.0, activation_r_multiple=1.0, trail_atr_multiple=2.0)
    assert wider_vol.current_stop_price == 104.0  # 110 - 2*3


def test_zero_initial_stop_distance_is_a_noop():
    state = _state(entry=100.0, initial_stop=100.0)
    updated = update_trailing_stop(state, current_price=110.0, current_atr=1.0, activation_r_multiple=1.0, trail_atr_multiple=2.0)
    assert updated == state


def test_trailing_stop_hit_returns_false_before_activation():
    state = _state()  # not activated
    assert trailing_stop_hit(state, bar_low=90.0, bar_high=91.0) is False


def test_trailing_stop_hit_true_when_bar_low_crosses_long_stop():
    state = _state(activated=True, current_stop=103.0)
    assert trailing_stop_hit(state, bar_low=102.0, bar_high=106.0) is True


def test_trailing_stop_hit_false_when_bar_stays_above_long_stop():
    state = _state(activated=True, current_stop=103.0)
    assert trailing_stop_hit(state, bar_low=104.0, bar_high=106.0) is False


def test_trailing_stop_hit_true_when_bar_high_crosses_short_stop():
    state = _state(side="short", entry=100.0, initial_stop=105.0, activated=True, current_stop=97.0)
    assert trailing_stop_hit(state, bar_low=93.0, bar_high=98.0) is True


def test_split_divides_stake_risk_and_target_proportionally():
    result = split_stake_for_partial_close(
        stake=100.0, risk_amount=10.0, take_profit_amount=20.0,
        partial_close_fraction=0.5, min_stake=1.0,
    )
    assert result is not None
    scalp, runner = result
    assert scalp["stake"] == 50.0
    assert runner["stake"] == 50.0
    assert scalp["risk_amount"] == 5.0
    assert runner["risk_amount"] == 5.0
    assert scalp["take_profit_amount"] == 10.0


def test_split_runner_take_profit_is_a_wide_backstop_not_the_real_target():
    result = split_stake_for_partial_close(
        stake=100.0, risk_amount=10.0, take_profit_amount=20.0,
        partial_close_fraction=0.5, min_stake=1.0, runner_backstop_multiple=10.0,
    )
    scalp, runner = result
    # runner's proportional target would be 10.0 (same math as scalp);
    # the backstop must be far wider, not equal to it.
    assert runner["take_profit_amount"] == 100.0  # 10.0 * 10.0
    assert runner["take_profit_amount"] > scalp["take_profit_amount"] * 5


def test_split_returns_none_when_scalp_leg_would_be_below_min_stake():
    result = split_stake_for_partial_close(
        stake=10.0, risk_amount=1.0, take_profit_amount=2.0,
        partial_close_fraction=0.05, min_stake=1.0,  # scalp leg = 0.5, below min_stake
    )
    assert result is None


def test_split_returns_none_when_runner_leg_would_be_below_min_stake():
    result = split_stake_for_partial_close(
        stake=10.0, risk_amount=1.0, take_profit_amount=2.0,
        partial_close_fraction=0.95, min_stake=1.0,  # runner leg = 0.5, below min_stake
    )
    assert result is None


def test_split_stakes_sum_back_to_the_original_total():
    result = split_stake_for_partial_close(
        stake=33.33, risk_amount=3.33, take_profit_amount=6.66,
        partial_close_fraction=0.4, min_stake=1.0,
    )
    scalp, runner = result
    assert round(scalp["stake"] + runner["stake"], 2) == 33.33
    assert round(scalp["risk_amount"] + runner["risk_amount"], 2) == 3.33

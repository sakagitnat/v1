import math

import pytest

from trading.cfd.deflated_sharpe import (
    annualized_to_per_period,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
)


def test_annualized_to_per_period_round_trips():
    per_period = annualized_to_per_period(2.0, periods_per_year=252)
    assert per_period == pytest.approx(2.0 / math.sqrt(252))


def test_annualized_to_per_period_zero_periods_is_safe():
    assert annualized_to_per_period(2.0, periods_per_year=0) == 0.0


def test_psr_is_half_when_observed_equals_benchmark():
    # z-score is exactly 0 -- no evidence either way.
    assert probabilistic_sharpe_ratio(1.0, benchmark_sr=1.0, n_obs=100) == pytest.approx(0.5)


def test_psr_rises_with_more_observations_for_the_same_edge():
    few = probabilistic_sharpe_ratio(1.0, benchmark_sr=0.0, n_obs=30)
    many = probabilistic_sharpe_ratio(1.0, benchmark_sr=0.0, n_obs=500)
    assert many > few


def test_psr_short_track_record_returns_no_information():
    assert probabilistic_sharpe_ratio(5.0, benchmark_sr=0.0, n_obs=1) == 0.5


def test_psr_negative_skew_penalizes_a_positive_sharpe():
    # Negative skew makes a given positive Sharpe less trustworthy
    # (crash risk hiding in the tail) -- PSR should come out lower.
    symmetric = probabilistic_sharpe_ratio(1.0, 0.0, n_obs=100, skew=0.0, kurtosis=3.0)
    neg_skew = probabilistic_sharpe_ratio(1.0, 0.0, n_obs=100, skew=-2.0, kurtosis=3.0)
    assert neg_skew < symmetric


def test_expected_max_sharpe_zero_for_no_dispersion_or_one_trial():
    assert expected_max_sharpe(sr_std=0.0, n_trials=100) == 0.0
    assert expected_max_sharpe(sr_std=1.0, n_trials=1) == 0.0
    assert expected_max_sharpe(sr_std=1.0, n_trials=0) == 0.0


def test_expected_max_sharpe_grows_with_trial_count():
    small_n = expected_max_sharpe(sr_std=0.5, n_trials=10)
    large_n = expected_max_sharpe(sr_std=0.5, n_trials=1000)
    assert 0.0 < small_n < large_n


def test_deflated_sharpe_ratio_falls_as_trial_count_grows():
    # The core DSR property this whole module exists for: the exact same
    # observed result gets LESS credible, not more, as more parameter
    # combinations were searched to find it.
    common = dict(observed_sr=0.3, sr_trials_std=0.4, n_obs=200)
    dsr_few_trials = deflated_sharpe_ratio(n_trials=5, **common)
    dsr_many_trials = deflated_sharpe_ratio(n_trials=500, **common)
    assert dsr_many_trials < dsr_few_trials


def test_deflated_sharpe_ratio_matches_psr_with_one_trial():
    # n_trials=1 means expected_max_sharpe is 0 -- no multiple-testing
    # penalty -- so DSR collapses to plain PSR against a zero benchmark.
    dsr = deflated_sharpe_ratio(observed_sr=0.3, sr_trials_std=0.4, n_trials=1, n_obs=200)
    psr = probabilistic_sharpe_ratio(0.3, benchmark_sr=0.0, n_obs=200)
    assert dsr == pytest.approx(psr)


def test_deflated_sharpe_ratio_returns_probability_in_unit_interval():
    result = deflated_sharpe_ratio(observed_sr=2.5, sr_trials_std=0.3, n_trials=243, n_obs=80)
    assert 0.0 <= result <= 1.0

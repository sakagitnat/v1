"""Deflated Sharpe Ratio (DSR) -- Bailey & Lopez de Prado's correction for
multiple-testing / selection bias in a parameter grid search.

Every optimize_cfd_*.py script in this project already does the right
thing about *one* kind of overfitting: it never trusts a TRAIN-only
result, always checking the winning candidate against an untouched TEST
split. But TRAIN/TEST alone says nothing about a *different* kind of
overfitting -- picking the best of N tested parameter combinations
inflates the winner's Sharpe ratio above its true expected value purely
from how many hypotheses were tried, even if every single one of them
was backtested completely honestly. A grid of 243 combinations will
turn up an attractive-looking winner from pure noise far more often
than a grid of 10 does, for exactly the same underlying (non-)edge.
DSR corrects for this: it asks "what's the probability this strategy's
Sharpe ratio is genuine skill, rather than the best of N noisy draws?"
-- a number that gets *harder* to clear as N grows, not easier, which
plain Sharpe (or even TRAIN/TEST) never penalizes.

Reference: Bailey, D. and Lopez de Prado, M. (2014), "The Deflated
Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and
Non-Normality", Journal of Portfolio Management.

All Sharpe ratios in this module are *per-period* (the same periodicity
as the returns they were computed from), not annualized -- the
probabilistic Sharpe ratio's standard error depends on the number of
return observations T, which only lines up with the Sharpe estimator's
own variance at the native sampling frequency. annualized_to_per_period()
converts the annualized Sharpe this project's compute_cfd_metrics()
reports back to that native frequency before anything else here touches
it.
"""
import math

EULER_MASCHERONI = 0.5772156649015329


def annualized_to_per_period(annualized_sharpe: float, periods_per_year: float) -> float:
    """Inverse of the `sharpe * sqrt(periods_per_year)` annualization
    trading.cfd.backtest.compute_cfd_metrics() applies."""
    if periods_per_year <= 0:
        return 0.0
    return annualized_sharpe / math.sqrt(periods_per_year)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (probit), via Acklam's rational
    approximation -- scipy isn't a dependency here, and this is accurate
    to ~1e-9, far tighter than this module's other inputs (sample
    skew/kurtosis of a few dozen trades) ever justify."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")

    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]

    p_low = 0.02425
    p_high = 1 - p_low

    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
    )


def probabilistic_sharpe_ratio(
    observed_sr: float,
    benchmark_sr: float,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """P(true Sharpe > benchmark_sr), given an observed per-period Sharpe
    estimated from n_obs return observations with the given sample skew
    (0 = symmetric) and kurtosis (3 = normal -- NOT excess kurtosis).
    This is PSR; DSR is just PSR with benchmark_sr set to the expected
    maximum Sharpe of N trials under the null (expected_max_sharpe()
    below), which is what deflated_sharpe_ratio() does.

    n_obs < 2 returns 0.5 (no information -- not 0.0, which would wrongly
    say "definitely not skill" for a track record too short to say
    anything)."""
    if n_obs < 2:
        return 0.5
    denom = 1 - skew * observed_sr + ((kurtosis - 1) / 4) * observed_sr**2
    if denom <= 0:
        # Pathological skew/kurtosis combination for this SR -- the
        # Gaussian approximation underlying PSR breaks down here, not a
        # real "infinitely confident" result.
        return float("nan")
    z = (observed_sr - benchmark_sr) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return _norm_cdf(z)


def expected_max_sharpe(sr_std: float, n_trials: int) -> float:
    """E[max of N trial Sharpe ratios] under the null that all N were
    drawn from a mean-zero distribution with standard deviation sr_std
    (the actual observed cross-sectional std of the N trials' Sharpes is
    what's passed in -- this is the standard Bailey/Lopez de Prado
    closed-form approximation for the expectation of an extreme value,
    not a simulation). N=0 or 1 trial has no multiple-testing penalty to
    apply, so returns 0.0 (no deflation)."""
    if n_trials <= 1 or sr_std <= 0:
        return 0.0
    return sr_std * (
        (1 - EULER_MASCHERONI) * _norm_ppf(1 - 1 / n_trials)
        + EULER_MASCHERONI * _norm_ppf(1 - 1 / (n_trials * math.e))
    )


def deflated_sharpe_ratio(
    observed_sr: float,
    sr_trials_std: float,
    n_trials: int,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """P(this strategy's true Sharpe exceeds what pure luck across
    n_trials noisy parameter combinations would be expected to produce
    anyway). All Sharpe-ratio arguments (observed_sr, sr_trials_std) are
    per-period, not annualized -- see module docstring.

    Interpretation: DSR is a probability (0-1), not a ratio despite the
    name (same convention as the Bailey/Lopez de Prado paper). Above
    ~0.95 is the usual "genuinely looks like skill" bar; this project
    additionally always requires the TRAIN/TEST gate in
    optimize_cfd_strategy.py to pass too -- DSR and TRAIN/TEST catch
    different failure modes (selection-bias-across-trials vs.
    curve-fit-to-TRAIN) and neither substitutes for the other."""
    benchmark = expected_max_sharpe(sr_trials_std, n_trials)
    return probabilistic_sharpe_ratio(observed_sr, benchmark, n_obs, skew, kurtosis)

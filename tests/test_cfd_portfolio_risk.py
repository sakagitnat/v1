from trading.cfd.portfolio_risk import (
    OpenRiskPosition,
    PortfolioRiskCeilings,
    check_new_position,
    factor_exposures,
    thesis_key,
)


def _ceilings(thesis=0.02, correlated=0.03, portfolio=0.05, leverage=10.0):
    return PortfolioRiskCeilings(
        max_thesis_risk_pct=thesis,
        max_correlated_risk_pct=correlated,
        max_portfolio_risk_pct=portfolio,
        max_exposure_multiple=leverage,
    )


def _pos(instrument, side, risk_amount, notional=0.0, contract_id=1):
    return OpenRiskPosition(
        contract_id=contract_id, instrument=instrument, side=side,
        risk_amount=risk_amount, notional=notional,
    )


def test_thesis_key_is_instrument_and_side():
    assert thesis_key("frxXAUUSD", "long") == "frxXAUUSD:long"
    assert thesis_key("frxXAUUSD", "long") != thesis_key("frxXAUUSD", "short")


def test_factor_exposures_short_flips_the_sign():
    long_exp = factor_exposures("frxXAUUSD", "long")
    short_exp = factor_exposures("frxXAUUSD", "short")
    assert long_exp["usd"] == -short_exp["usd"]


def test_unmapped_instrument_has_no_factor_exposure():
    assert factor_exposures("frxUnknownPair", "long") == {}


def test_new_position_with_no_open_positions_is_allowed():
    result = check_new_position([], "frxXAUUSD", "long", 1.0, 20.0, 100.0, _ceilings())
    assert result is None


def test_zero_or_negative_equity_is_rejected():
    result = check_new_position([], "frxXAUUSD", "long", 1.0, 20.0, 0.0, _ceilings())
    assert result is not None
    assert "equity" in result


def test_same_instrument_same_side_breaches_thesis_ceiling():
    # 2% thesis ceiling on $100 equity = $2. One $1.50 position already
    # open on the same thesis; a second $1 position would push it to
    # $2.50, over the ceiling.
    existing = [_pos("frxXAUUSD", "long", risk_amount=1.5, contract_id=1)]
    result = check_new_position(existing, "frxXAUUSD", "long", 1.0, 20.0, 100.0, _ceilings(thesis=0.02))
    assert result is not None
    assert "thesis" in result
    assert "frxXAUUSD:long" in result


def test_same_instrument_opposite_side_is_a_different_thesis():
    # A long and a short on the same instrument are different theses --
    # must not be summed together for the thesis ceiling.
    existing = [_pos("frxXAUUSD", "long", risk_amount=1.5, contract_id=1)]
    result = check_new_position(existing, "frxXAUUSD", "short", 1.0, 20.0, 100.0, _ceilings(thesis=0.02))
    assert result is None


def test_correlated_instruments_same_direction_breach_correlated_ceiling():
    # frxXAUUSD long and frxEURUSD long are both "USD weakens" bets (same
    # sign on the "usd" factor -- signed exposure -1, grouped "usd:short"
    # since both benefit when USD falls) -- 3% correlated ceiling on $100
    # equity = $3.
    existing = [_pos("frxXAUUSD", "long", risk_amount=2.0, contract_id=1)]
    result = check_new_position(existing, "frxEURUSD", "long", 1.5, 20.0, 100.0, _ceilings(correlated=0.03))
    assert result is not None
    assert "correlated" in result
    assert "usd:short" in result


def test_correlated_instruments_are_capped_separately_from_thesis():
    # Different instruments never share a thesis bucket even if they
    # share a correlation factor -- confirms the thesis check alone
    # wouldn't have caught this (only the correlated check does).
    existing = [_pos("frxXAUUSD", "long", risk_amount=2.0, contract_id=1)]
    assert thesis_key("frxXAUUSD", "long") != thesis_key("frxEURUSD", "long")


def test_natural_hedge_on_same_factor_does_not_inflate_correlated_risk():
    # frxUSDJPY long is a "USD strengthens" bet -- opposite sign on the
    # "usd" factor from frxXAUUSD long ("USD weakens") -- must be tracked
    # in a separate group, never summed with it. Thesis/portfolio ceilings
    # raised so only the correlated check under test can bind.
    existing = [_pos("frxXAUUSD", "long", risk_amount=2.5, contract_id=1)]
    result = check_new_position(
        existing, "frxUSDJPY", "long", 2.5, 20.0, 100.0,
        _ceilings(thesis=0.10, correlated=0.03, portfolio=0.10),
    )
    assert result is None  # would be rejected if wrongly summed (5% > 3%)


def test_unmapped_instrument_never_breaches_correlated_ceiling():
    existing = [_pos("frxXAUUSD", "long", risk_amount=2.5, contract_id=1)]
    result = check_new_position(
        existing, "frxUnknownPair", "long", 2.5, 20.0, 100.0,
        _ceilings(thesis=0.10, correlated=0.03, portfolio=0.10),
    )
    assert result is None


def test_diverse_independent_positions_breach_total_portfolio_ceiling_not_correlated():
    # Five different, mutually uncorrelated-by-this-map instruments each
    # risking 1.2% -- none breach thesis or correlated ceilings alone, but
    # their sum (6%) breaches the 5% portfolio ceiling.
    existing = [
        _pos("frxXAUUSD", "long", risk_amount=1.2, contract_id=1),
        _pos("frxEURUSD", "short", risk_amount=1.2, contract_id=2),  # opposite sign on usd -- different group
        _pos("frxUSDJPY", "short", risk_amount=1.2, contract_id=3),
        _pos("cryBTCUSD", "long", risk_amount=1.2, contract_id=4),  # unmapped -- no factor exposure
    ]
    result = check_new_position(existing, "cryETHUSD", "long", 1.2, 20.0, 100.0, _ceilings(portfolio=0.05))
    assert result is not None
    assert "portfolio" in result


def test_five_genuinely_independent_one_percent_positions_fit_the_default_portfolio_ceiling():
    # docs/VISION.md's own worked example: five $1 positions on $100
    # equity (5%) must fit the default 5% portfolio ceiling exactly.
    existing = [
        _pos("frxXAUUSD", "long", risk_amount=1.0, contract_id=1),
        _pos("frxEURUSD", "short", risk_amount=1.0, contract_id=2),
        _pos("frxUSDJPY", "short", risk_amount=1.0, contract_id=3),
        _pos("cryBTCUSD", "long", risk_amount=1.0, contract_id=4),
    ]
    result = check_new_position(existing, "cryETHUSD", "long", 1.0, 20.0, 100.0, _ceilings())
    assert result is None


def test_leverage_ceiling_rejects_excess_notional_even_with_low_risk_dollars():
    # A wide stop means a small risk_amount can still carry huge notional
    # (Deriv's multiplier) -- the leverage ceiling must catch this even
    # when every risk-dollar ceiling above is nowhere close to binding.
    existing = [_pos("frxXAUUSD", "long", risk_amount=0.1, notional=500.0, contract_id=1)]
    result = check_new_position(existing, "frxEURUSD", "short", 0.1, 600.0, 100.0, _ceilings(leverage=10.0))
    assert result is not None
    assert "leverage" in result or "exposure" in result


def test_leverage_ceiling_allows_exposure_within_the_multiple():
    existing = [_pos("frxXAUUSD", "long", risk_amount=0.1, notional=300.0, contract_id=1)]
    result = check_new_position(existing, "frxEURUSD", "short", 0.1, 300.0, 100.0, _ceilings(leverage=10.0))
    assert result is None


def test_position_with_no_recorded_notional_does_not_falsely_trip_leverage_ceiling():
    # Backward compatibility: a position recorded before the notional
    # field existed defaults to 0.0 -- must count toward risk ceilings but
    # never phantom-inflate the leverage figure.
    existing = [_pos("frxXAUUSD", "long", risk_amount=0.1, notional=0.0, contract_id=1)]
    result = check_new_position(existing, "frxEURUSD", "short", 0.1, 50.0, 100.0, _ceilings(leverage=10.0))
    assert result is None


def test_rejection_reasons_are_checked_in_a_stable_order():
    # thesis is checked before correlated/portfolio/leverage -- a position
    # that breaches multiple ceilings at once reports the first one found.
    existing = [_pos("frxXAUUSD", "long", risk_amount=5.0, contract_id=1)]
    result = check_new_position(existing, "frxXAUUSD", "long", 5.0, 20.0, 100.0, _ceilings())
    assert "thesis" in result

from trading.risk.ratchet import maybe_ratchet_floor


def test_no_ratchet_without_a_floor():
    assert maybe_ratchet_floor(equity=150, capital_floor=None, trigger_pct=0.20, bank_fraction=0.5) is None


def test_no_ratchet_below_trigger():
    # equity is only 10% above the floor; trigger requires 20%
    assert maybe_ratchet_floor(equity=110, capital_floor=100, trigger_pct=0.20, bank_fraction=0.5) is None


def test_no_ratchet_when_equity_at_or_below_floor():
    assert maybe_ratchet_floor(equity=100, capital_floor=100, trigger_pct=0.20, bank_fraction=0.5) is None
    assert maybe_ratchet_floor(equity=90, capital_floor=100, trigger_pct=0.20, bank_fraction=0.5) is None


def test_ratchet_banks_half_the_excess_by_default():
    # equity is 30% above the floor -- past the 20% trigger
    new_floor = maybe_ratchet_floor(equity=130, capital_floor=100, trigger_pct=0.20, bank_fraction=0.5)
    assert new_floor == 115.0  # 100 + 0.5 * 30


def test_ratchet_respects_custom_bank_fraction():
    new_floor = maybe_ratchet_floor(equity=200, capital_floor=100, trigger_pct=0.20, bank_fraction=0.25)
    assert new_floor == 125.0  # 100 + 0.25 * 100


def test_ratchet_clips_to_cap():
    # uncapped this would bank to 100 + 0.5*100 = 150, past the 120 cap
    new_floor = maybe_ratchet_floor(equity=200, capital_floor=100, trigger_pct=0.20, bank_fraction=0.5, cap=120)
    assert new_floor == 120.0


def test_no_ratchet_once_floor_is_already_at_the_cap():
    new_floor = maybe_ratchet_floor(equity=500, capital_floor=200, trigger_pct=0.20, bank_fraction=0.5, cap=200)
    assert new_floor is None


def test_no_ratchet_when_floor_exceeds_cap_somehow():
    new_floor = maybe_ratchet_floor(equity=500, capital_floor=250, trigger_pct=0.20, bank_fraction=0.5, cap=200)
    assert new_floor is None


def test_ratchet_below_cap_unaffected_by_cap():
    new_floor = maybe_ratchet_floor(equity=130, capital_floor=100, trigger_pct=0.20, bank_fraction=0.5, cap=200)
    assert new_floor == 115.0

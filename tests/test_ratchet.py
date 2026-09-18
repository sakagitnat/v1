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

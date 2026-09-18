from typing import Optional


def maybe_ratchet_floor(
    equity: float, capital_floor: Optional[float], trigger_pct: float, bank_fraction: float
) -> Optional[float]:
    """If a capital floor is set and equity has grown `trigger_pct` above
    it, raise the floor by `bank_fraction` of that excess -- "banking" part
    of the gain by protecting it with the new, higher floor, while leaving
    the rest as a cushion the strategy can keep trading with.

    Returns the new floor to persist, or None if no ratchet is due.
    """
    if capital_floor is None or capital_floor <= 0:
        return None
    excess = equity - capital_floor
    if excess <= 0 or excess / capital_floor < trigger_pct:
        return None
    return capital_floor + excess * bank_fraction

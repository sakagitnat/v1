import json
from pathlib import Path

_POSITIONS_PATH = Path(__file__).resolve().parents[3] / "state" / "positions.json"


def load_positions() -> dict:
    """Symbol -> {"qty": float, "stop_price": float, "target_price": float}
    for fractional-share positions the bot opened. Needed because Alpaca's
    bracket order class (which would otherwise track this for us) doesn't
    support fractional/notional orders -- see broker.py."""
    if not _POSITIONS_PATH.exists():
        return {}
    return json.loads(_POSITIONS_PATH.read_text())


def save_positions(positions: dict) -> None:
    _POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _POSITIONS_PATH.write_text(json.dumps(positions, indent=2) + "\n")


def record_open(symbol: str, qty: float, stop_price: float, target_price: float) -> None:
    positions = load_positions()
    positions[symbol] = {"qty": qty, "stop_price": stop_price, "target_price": target_price}
    save_positions(positions)


def record_close(symbol: str) -> None:
    positions = load_positions()
    positions.pop(symbol, None)
    save_positions(positions)

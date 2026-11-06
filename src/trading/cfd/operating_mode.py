"""Operating Modes -- src/trading/cfd/operating_mode.py

docs/VISION.md calls for Defensive/Normal/Aggressive/Recovery/Paused
operating modes, "but every mode must stay under hard risk limits."
Paused already exists (trading.cfd.state's `paused` flag -- stops
trading entirely) -- this module covers the other four, which scale HOW
aggressively the bot sizes new entries while it's still trading, never
whether it trades at all.

Each mode is a fixed, pre-approved risk multiplier -- "ปรับ parameter
ภายในขอบเขตที่ปลอดภัย" (adjust parameters within a safe range), not an
open-ended dial. Recovery and Defensive deliberately use the SAME
conservative multiplier: Recovery means "trade smaller because equity is
under strain," never "trade bigger to catch up on losses faster" -- the
latter is exactly the revenge-trading/martingale pattern docs/VISION.md
forbids outright. The two exist as distinct, separately-loggable states
(so *why* the bot is being conservative -- market conditions vs. equity
strain -- stays visible in state/cfd_bot_state.json and the logs) even
though their numeric effect is identical today.

Aggressive's multiplier is still capped by CFD_MAX_RISK_PER_TRADE_CEILING
-- an ABSOLUTE ceiling no mode, current or future, may ever cross,
enforced here regardless of what CFD_RISK_PER_TRADE and the mode
multiplier would otherwise compute to.
"""
from typing import Optional

from trading.config import settings

DEFENSIVE = "defensive"
NORMAL = "normal"
AGGRESSIVE = "aggressive"
RECOVERY = "recovery"

VALID_MODES = (DEFENSIVE, NORMAL, AGGRESSIVE, RECOVERY)

_RISK_MULTIPLIER = {
    DEFENSIVE: 0.5,
    NORMAL: 1.0,
    AGGRESSIVE: 1.5,
    RECOVERY: 0.5,
}
_MAX_POSITIONS_MULTIPLIER = {
    DEFENSIVE: 0.5,
    NORMAL: 1.0,
    AGGRESSIVE: 1.0,  # deliberately not also raised -- risk_per_trade already scales up; don't compound with more concurrent exposure too
    RECOVERY: 0.5,
}


def _check_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown operating mode {mode!r} -- must be one of {VALID_MODES}")


def effective_risk_per_trade(mode: str, base_risk_per_trade: Optional[float] = None) -> float:
    _check_mode(mode)
    base = base_risk_per_trade if base_risk_per_trade is not None else settings.cfd_risk_per_trade
    scaled = base * _RISK_MULTIPLIER[mode]
    return min(scaled, settings.cfd_max_risk_per_trade_ceiling)


def effective_max_open_positions(mode: str, base_max_open_positions: Optional[int] = None) -> int:
    _check_mode(mode)
    base = base_max_open_positions if base_max_open_positions is not None else settings.cfd_max_open_positions
    scaled = int(base * _MAX_POSITIONS_MULTIPLIER[mode])
    return max(1, min(scaled, base))

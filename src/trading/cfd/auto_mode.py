"""Autonomous operating-mode selection that can only reduce risk.

The AI may move risk down without approval. It never selects AGGRESSIVE;
moving risk upward remains a human-controlled action.
"""
from __future__ import annotations
from trading.cfd.operating_mode import DEFENSIVE, NORMAL, RECOVERY

def choose_autonomous_mode(drawdown_tier: str, current_mode: str) -> tuple[str, str]:
    tier = (drawdown_tier or "normal").lower()
    if tier in {"severe", "deep"}:
        return RECOVERY, f"auto recovery: drawdown tier={tier}"
    if tier == "moderate":
        return DEFENSIVE, "auto defensive: moderate drawdown"
    # Never auto-raise from defensive/recovery/aggressive to normal. Returning
    # current mode preserves the human-approved risk posture.
    return current_mode, "no autonomous risk increase"

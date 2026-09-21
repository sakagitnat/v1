"""Append-only decision log for every CFD opportunity evaluation.

Separate from the closed-trade database: records TRADE / NO_TRADE / REJECTED /
ERROR decisions so the manager can learn from opportunities it deliberately
skipped, not only from positions that were opened and later closed.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_PATH = Path(__file__).resolve().parents[3] / "state" / "cfd_decisions.jsonl"

def record_decision(
    instrument: str,
    outcome: str,
    reason: str,
    *,
    regime: Optional[str] = None,
    strategy: Optional[str] = None,
    run_id: Optional[str] = None,
    bridge_command_id: Optional[str] = None,
) -> dict:
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instrument": instrument,
        "outcome": outcome,
        "reason": reason,
        "regime": regime,
        "strategy": strategy,
        "run_id": run_id,
        "bridge_command_id": bridge_command_id,
    }
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with _PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return row

def load_decisions() -> list[dict]:
    if not _PATH.exists():
        return []
    rows = []
    for line in _PATH.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

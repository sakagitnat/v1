"""Structured incident telemetry for CFD execution and data quality."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_PATH = Path(__file__).resolve().parents[3] / "state" / "cfd_incidents.jsonl"

KINDS = {
    "scheduler_exception",
    "broker_error",
    "data_quality",
    "duplicate_prevented",
    "foreign_position",
    "risk_control",
    "event_blackout",
    "execution_quality",
}

def record_incident(
    kind: str,
    *,
    severity: str,
    message: str,
    instrument: Optional[str] = None,
    correlation_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown incident kind: {kind}")
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "severity": severity,
        "message": message,
        "instrument": instrument,
        "correlation_id": correlation_id,
        "metadata": metadata or {},
    }
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with _PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return row

def load_incidents() -> list[dict]:
    if not _PATH.exists():
        return []
    return [json.loads(x) for x in _PATH.read_text().splitlines() if x.strip()]

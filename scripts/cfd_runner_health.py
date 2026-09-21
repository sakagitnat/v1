"""Health check for the autonomous Deriv DEMO scheduler.

A stale heartbeat during the expected XAUUSD market window is actionable:
a watchdog workflow may run the exact same deterministic scheduler as a
recovery attempt. Outside the expected market window it reports healthy/no-op.

Trading hours are intentionally conservative around Deriv's published XAUUSD
hours (GMT/UTC): Sun 22:10 - Fri 20:45, with a daily break 20:59 - 22:05.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.cfd_scheduler_heartbeat import HEARTBEAT_PATH, load_heartbeat


def expected_market_window(now: datetime) -> bool:
    now = now.astimezone(timezone.utc)
    weekday = now.weekday()  # Monday=0 ... Sunday=6
    clock = now.time().replace(tzinfo=None)

    if weekday == 5:  # Saturday
        return False
    if weekday == 6:  # Sunday
        return clock >= time(22, 10)
    if weekday == 4:  # Friday
        return clock <= time(20, 45)

    # Monday-Thursday. Stay out of the published daily XAUUSD break.
    return clock <= time(20, 59) or clock >= time(22, 5)


def heartbeat_age_minutes(data: dict, now: datetime) -> float | None:
    stamp = data.get("last_update_at")
    if not stamp:
        return None
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 60.0)


def assess(now: datetime, max_age_minutes: float, path: Path = HEARTBEAT_PATH) -> dict:
    if not expected_market_window(now):
        return {"healthy": True, "market_expected_open": False, "reason": "outside_expected_market_window"}

    data = load_heartbeat(path)
    age = heartbeat_age_minutes(data, now)
    if age is None:
        return {"healthy": False, "market_expected_open": True, "reason": "heartbeat_missing"}

    healthy = age <= max_age_minutes and data.get("status") != "failure"
    reason = "fresh" if healthy else ("last_run_failed" if data.get("status") == "failure" else "heartbeat_stale")
    return {
        "healthy": healthy,
        "market_expected_open": True,
        "reason": reason,
        "age_minutes": round(age, 2),
        "status": data.get("status"),
        "run_id": data.get("run_id"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-minutes", type=float, default=40.0)
    args = parser.parse_args()
    result = assess(datetime.now(timezone.utc), args.max_age_minutes)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["healthy"] else 2)


if __name__ == "__main__":
    main()

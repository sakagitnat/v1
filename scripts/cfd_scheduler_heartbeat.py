"""Durable scheduler heartbeat for the autonomous Deriv DEMO runner.

The trading workflow writes this file on every attempted run, including failed
runs. It is deliberately secret-free and lives beside the other CFD state so
operators can distinguish "NO TRADE" from "the scheduler never ran".
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_PATH = Path("state/cfd_scheduler_heartbeat.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_heartbeat(path: Path = HEARTBEAT_PATH) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("heartbeat state must be a JSON object")
    return data


def mark(status: str, *, path: Path = HEARTBEAT_PATH) -> dict:
    if status not in {"started", "success", "failure"}:
        raise ValueError(f"unsupported heartbeat status: {status}")

    # This file is the authoritative trading-runtime heartbeat. Do not let
    # CI/research/helper workflows overwrite it and make a non-trading run
    # look like a scheduler run.
    workflow = os.environ.get("GITHUB_WORKFLOW")
    expected_workflow = os.environ.get("CFD_HEARTBEAT_OWNER", "CFD Trading (Deriv)")
    if workflow and workflow != expected_workflow:
        raise RuntimeError(
            f"refusing to write scheduler heartbeat from workflow {workflow!r}; "
            f"owner is {expected_workflow!r}"
        )

    data = load_heartbeat(path)
    now = _now_iso()
    data.update(
        {
            "status": status,
            "last_update_at": now,
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "event_name": os.environ.get("GITHUB_EVENT_NAME"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
            "runtime_ref": os.environ.get("CFD_RUNTIME_REF"),
        }
    )
    if status == "started":
        data["last_started_at"] = now
    elif status == "success":
        data["last_completed_at"] = now
        data["last_success_at"] = now
    else:
        data["last_completed_at"] = now
        data["last_failure_at"] = now

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("status", choices=["started", "success", "failure"])
    args = parser.parse_args()
    print(json.dumps(mark(args.status), sort_keys=True))


if __name__ == "__main__":
    main()

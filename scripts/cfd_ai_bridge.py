"""Secure parser/reservation helper for the ChatGPT -> GitHub -> Deriv DEMO bridge.

This module intentionally does NOT place orders itself. It validates a narrow
GitHub issue-comment command, reserves the command id for replay protection,
and lets the existing CFD scheduler perform the actual evaluation/execution.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from uuid import UUID

STATE_PATH = Path("state/cfd_ai_bridge_commands.json")
COMMAND_RE = re.compile(
    r"^AI_EXECUTE_DEMO command_id=([0-9a-fA-F-]{36}) intent=(evaluate)$"
)
ALLOWED_ACTOR = "sakagitnat"
ALLOWED_ISSUE = 5


class BridgeCommandError(RuntimeError):
    pass


def parse_command(body: str, actor: str, issue_number: int) -> tuple[str, str]:
    if actor != ALLOWED_ACTOR:
        raise BridgeCommandError(f"unauthorized actor: {actor}")
    if issue_number != ALLOWED_ISSUE:
        raise BridgeCommandError(f"unauthorized issue: {issue_number}")

    match = COMMAND_RE.fullmatch((body or "").strip())
    if not match:
        raise BridgeCommandError("command does not match the exact allowed grammar")

    command_id, intent = match.groups()
    # Canonical UUID validation prevents alternate malformed encodings.
    command_id = str(UUID(command_id))
    return command_id, intent


def _load_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {"commands": {}}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("commands", {}), dict):
        raise BridgeCommandError("invalid bridge state file")
    data.setdefault("commands", {})
    return data


def reserve(command_id: str, actor: str, intent: str, path: Path = STATE_PATH) -> None:
    state = _load_state(path)
    commands = state["commands"]
    if command_id in commands:
        raise BridgeCommandError(f"duplicate command_id: {command_id}")

    commands[command_id] = {
        "actor": actor,
        "intent": intent,
        "status": "reserved",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["validate", "reserve"])
    parser.add_argument("--body", default=os.environ.get("COMMENT_BODY", ""))
    parser.add_argument("--actor", default=os.environ.get("COMMENT_ACTOR", ""))
    parser.add_argument(
        "--issue-number",
        type=int,
        default=int(os.environ.get("ISSUE_NUMBER", "0")),
    )
    args = parser.parse_args()

    command_id, intent = parse_command(args.body, args.actor, args.issue_number)

    # Defense-in-depth: the workflow hardcodes this false too.
    if os.environ.get("CFD_ALLOW_LIVE_TRADING", "false").lower() != "false":
        raise BridgeCommandError("bridge refuses to run when live trading is enabled")

    if args.action == "reserve":
        reserve(command_id, args.actor, intent)

    print(json.dumps({"command_id": command_id, "intent": intent, "actor": args.actor}))


if __name__ == "__main__":
    main()

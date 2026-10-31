"""Runs the CFD/forex (Deriv) trading strategy once. Meant to be invoked
roughly hourly during market hours by a scheduled GitHub Actions
workflow -- see .github/workflows/cfd-trading.yml.

Completely separate from the stock system (run_paper_trading.py): separate
account, separate state file (state/cfd_bot_state.json), separate safety
gate (CFD_ALLOW_LIVE_TRADING -- see trading/cfd/broker.py for how Deriv's
account model makes this gate work differently from Alpaca/OANDA's).

Connection and order flow confirmed end-to-end against the real Deriv
API -- see src/trading/cfd/broker.py's docstring.

When BRIDGE_COMMAND_ID is set in the environment (only the CFD AI Demo
Bridge workflow does this -- see .github/workflows/cfd-ai-demo-bridge.yml),
threads that id through to run_once() and prints a BRIDGE_RESULT_JSON= line
to stdout with the per-instrument TRADE/NO_TRADE/REJECTED/ERROR summary it
returns, so a later workflow step can post it back to issue #5. If
run_once() itself raises, that's caught here and reported as an ERROR
result too -- only the exception's class name, never str(exc), which could
echo details from a broker/library error back into a public issue comment.
Exits 0 either way in bridge mode: the audit comment is the failure signal
there, not a red Actions run. The normal hourly schedule (BRIDGE_COMMAND_ID
unset) is untouched and still raises/fails loudly as before.

After run_once() finishes, also runs the three timeframe-champion
accounts without their own dedicated loop (M30/H4/D1 -- H1's champion,
core_h1, is what run_once() itself already trades). Always sequential,
in this same process, right after run_once() -- never a separately
scheduled workflow. Both read/write the same shared open_trades state,
and this is what actually guarantees neither ever executes concurrently
with the other (see trading.cfd.champion_scheduler's docstring). Skipped
entirely in bridge mode: the bridge's one-command-one-evaluation
contract is about run_once() specifically, and champions have no
command_id to attribute a result to.

Usage: python scripts/run_cfd_trading.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker
from trading.cfd.champion_scheduler import run_champions
from trading.cfd.scheduler import run_once


def run_bridge(command_id: str) -> dict:
    result = {"command_id": command_id, "run_id": os.environ.get("GITHUB_RUN_ID"), "status": "OK", "instruments": []}
    try:
        result["instruments"] = asyncio.run(run_once(command_id))
    except Exception as exc:  # noqa: BLE001 -- bridge audit must always produce a result, never a bare crash
        result["status"] = "ERROR"
        result["error"] = type(exc).__name__
    print(f"BRIDGE_RESULT_JSON={json.dumps(result)}")
    return result


async def run_normal() -> None:
    await run_once()
    broker = DerivBroker()
    try:
        await broker.connect()
        await run_champions(broker)
    finally:
        await broker.close()


if __name__ == "__main__":
    bridge_command_id = os.environ.get("BRIDGE_COMMAND_ID") or None
    if bridge_command_id:
        run_bridge(bridge_command_id)
    else:
        asyncio.run(run_normal())

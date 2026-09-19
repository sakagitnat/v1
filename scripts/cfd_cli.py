"""Manual control for the CFD/forex (Deriv) bot: status, pause/resume,
excluding an instrument. Mirrors scripts/cli.py's pattern for the stock
system but is a completely separate account/state file.

Meant to be run by a "CFD Manual Command" GitHub Actions workflow
(workflow_dispatch), triggered from chat -- never needs the Deriv token
directly, since it lives only in the repository's GitHub Actions secrets.

Instrument names are Deriv's own, mixed-case and case-sensitive
(e.g. frxXAUUSD for gold, not XAU_USD or FRXXAUUSD).

Usage:
  python scripts/cfd_cli.py status
  python scripts/cfd_cli.py pause [--reason "..."]
  python scripts/cfd_cli.py resume
  python scripts/cfd_cli.py exclude-instrument frxXAUUSD [--reason "..."]
  python scripts/cfd_cli.py include-instrument frxXAUUSD
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker
from trading.cfd.state import (
    exclude_instrument,
    include_instrument,
    load_state,
    set_paused,
)


async def cmd_status(_args):
    broker = DerivBroker()
    try:
        await broker.connect()
        state = load_state()
        equity = await broker.account_equity()
        positions = await broker.open_positions()

        pause_note = f" ({state.get('pause_reason')})" if state.get("paused") and state.get("pause_reason") else ""
        print(f"Paused: {state.get('paused', False)}{pause_note}")
        print(f"Equity: {equity:.2f}")
        print(f"Capital floor: {state.get('capital_floor')}")

        excluded = state.get("excluded_instruments") or {}
        if excluded:
            print(f"Excluded instruments: {excluded}")

        print(f"Open positions ({len(positions)}):")
        for instrument, pos in positions.items():
            print(f"  {instrument}: {pos['side']} (contract {pos['contract_id']})")
    finally:
        await broker.close()


def cmd_pause(args):
    set_paused(True, getattr(args, "reason", "") or "")
    print("Paused. The CFD bot will skip trading until resumed.")


def cmd_resume(_args):
    set_paused(False)
    print("Resumed. The CFD bot will trade again.")


def cmd_exclude_instrument(args):
    exclude_instrument(args.instrument, args.reason or "")
    print(f"{args.instrument} excluded from new entries until included again. Existing open positions are unaffected.")


def cmd_include_instrument(args):
    include_instrument(args.instrument)
    print(f"{args.instrument} is eligible for new entries again.")


def main():
    parser = argparse.ArgumentParser(description="Manual control for the CFD/forex bot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status, is_async=True)

    pause_parser = sub.add_parser("pause")
    pause_parser.add_argument("--reason", default="", help="Why (e.g. 'macro risk: unscheduled Fed announcement')")
    pause_parser.set_defaults(func=cmd_pause, is_async=False)

    sub.add_parser("resume").set_defaults(func=cmd_resume, is_async=False)

    exclude_parser = sub.add_parser("exclude-instrument")
    exclude_parser.add_argument("instrument")
    exclude_parser.add_argument("--reason", default="")
    exclude_parser.set_defaults(func=cmd_exclude_instrument, is_async=False)

    include_parser = sub.add_parser("include-instrument")
    include_parser.add_argument("instrument")
    include_parser.set_defaults(func=cmd_include_instrument, is_async=False)

    args = parser.parse_args()
    if args.is_async:
        asyncio.run(args.func(args))
    else:
        args.func(args)


if __name__ == "__main__":
    main()

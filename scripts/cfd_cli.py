"""Manual control for the CFD/forex (OANDA) bot: status, pause/resume,
excluding an instrument. Mirrors scripts/cli.py's pattern for the stock
system but is a completely separate account/state file.

Meant to be run by a "CFD Manual Command" GitHub Actions workflow
(workflow_dispatch), triggered from chat -- never needs the OANDA token
directly, since it lives only in the repository's GitHub Actions secrets.

Usage:
  python scripts/cfd_cli.py status
  python scripts/cfd_cli.py pause [--reason "..."]
  python scripts/cfd_cli.py resume
  python scripts/cfd_cli.py exclude-instrument XAU_USD [--reason "..."]
  python scripts/cfd_cli.py include-instrument XAU_USD
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import OandaBroker
from trading.cfd.state import (
    exclude_instrument,
    include_instrument,
    load_state,
    set_paused,
)


def cmd_status(_args):
    broker = OandaBroker()
    state = load_state()
    equity = broker.account_equity()
    positions = broker.open_positions()

    pause_note = f" ({state.get('pause_reason')})" if state.get("paused") and state.get("pause_reason") else ""
    print(f"Paused: {state.get('paused', False)}{pause_note}")
    print(f"Equity (NAV): {equity:.2f}")
    print(f"Capital floor: {state.get('capital_floor')}")

    excluded = state.get("excluded_instruments") or {}
    if excluded:
        print(f"Excluded instruments: {excluded}")

    print(f"Open positions ({len(positions)}):")
    for instrument, pos in positions.items():
        print(f"  {instrument}: {pos['side']} {pos['units']} units")


def cmd_pause(args):
    set_paused(True, getattr(args, "reason", "") or "")
    print("Paused. The CFD bot will skip trading until resumed.")


def cmd_resume(_args):
    set_paused(False)
    print("Resumed. The CFD bot will trade again.")


def cmd_exclude_instrument(args):
    instrument = args.instrument.upper()
    exclude_instrument(instrument, args.reason or "")
    print(f"{instrument} excluded from new entries until included again. Existing open positions are unaffected.")


def cmd_include_instrument(args):
    instrument = args.instrument.upper()
    include_instrument(instrument)
    print(f"{instrument} is eligible for new entries again.")


def main():
    parser = argparse.ArgumentParser(description="Manual control for the CFD/forex bot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    pause_parser = sub.add_parser("pause")
    pause_parser.add_argument("--reason", default="", help="Why (e.g. 'macro risk: unscheduled Fed announcement')")
    pause_parser.set_defaults(func=cmd_pause)

    sub.add_parser("resume").set_defaults(func=cmd_resume)

    exclude_parser = sub.add_parser("exclude-instrument")
    exclude_parser.add_argument("instrument")
    exclude_parser.add_argument("--reason", default="")
    exclude_parser.set_defaults(func=cmd_exclude_instrument)

    include_parser = sub.add_parser("include-instrument")
    include_parser.add_argument("instrument")
    include_parser.set_defaults(func=cmd_include_instrument)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

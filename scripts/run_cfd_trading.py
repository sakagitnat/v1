"""Runs the CFD/forex (Deriv) trading strategy once. Meant to be invoked
roughly hourly during market hours by a scheduled GitHub Actions
workflow -- see .github/workflows/cfd-trading.yml.

Completely separate from the stock system (run_paper_trading.py): separate
account, separate state file (state/cfd_bot_state.json), separate safety
gate (CFD_ALLOW_LIVE_TRADING -- see trading/cfd/broker.py for how Deriv's
account model makes this gate work differently from Alpaca/OANDA's).

Connection and order flow confirmed end-to-end against the real Deriv
API -- see src/trading/cfd/broker.py's docstring.

Usage: python scripts/run_cfd_trading.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.scheduler import run_once

if __name__ == "__main__":
    asyncio.run(run_once())

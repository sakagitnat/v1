"""Runs the CFD/forex (OANDA) trading strategy once. Meant to be invoked
every 15-30 minutes during market hours by a scheduled GitHub Actions
workflow -- see .github/workflows/cfd-trading.yml.

Completely separate from the stock system (run_paper_trading.py): separate
account, separate state file (state/cfd_bot_state.json), separate safety
gate (OANDA_PRACTICE / CFD_ALLOW_LIVE_TRADING).

UNTESTED against the real OANDA API as of writing -- see
src/trading/cfd/broker.py's docstring.

Usage: python scripts/run_cfd_trading.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.scheduler import run_once

if __name__ == "__main__":
    run_once()

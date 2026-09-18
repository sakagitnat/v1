"""Run one iteration of the strategy against Alpaca.

Refuses to touch a live (real-money) account unless ALPACA_PAPER=false and
ALLOW_LIVE_TRADING=true are both set explicitly — see trading/config.py.
Intended to run once per trading day via cron or a scheduled CI job.

Usage: python scripts/run_paper_trading.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.execution.scheduler import run_once

if __name__ == "__main__":
    run_once()

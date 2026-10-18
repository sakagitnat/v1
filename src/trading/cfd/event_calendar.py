"""Versioned official high-impact calendar snapshot for shadow attribution.

Sources are official BLS/Federal Reserve schedules. This does NOT yet block
entries; scheduler uses it to tag/measure event windows until the blackout
hypothesis clears the project's validation gate.
"""
from __future__ import annotations
from datetime import datetime, timezone
from trading.cfd.event_blackout import EconomicEvent

SNAPSHOT_VERSION = "2026-09-21"
SOURCES = {
    "BLS": "https://www.bls.gov/schedule/2026/10_sched_list.htm",
    "FOMC": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
}

# October is EDT (UTC-4) until Nov 1, 2026.
EVENTS = [
    EconomicEvent("US Employment Situation (NFP)", datetime(2026, 10, 2, 12, 30, tzinfo=timezone.utc)),
    EconomicEvent("US CPI", datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc)),
    EconomicEvent("FOMC decision / press conference", datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)),
]

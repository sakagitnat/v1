"""Multi-timeframe observation collector for the virtual-account lab.

This deliberately collects data before claiming an edge. M15/M5/M1 accounts
start in SHADOW mode: we record market context and EMA-crossover signal state,
but never place a broker order from these observations. That lets later
validation use genuine forward data without contaminating the ACTIVE H1 system.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from trading.cfd.regime import classify_regime, classify_volatility
from trading.cfd.strategy import EmaCrossoverStrategy
from trading.cfd.virtual_accounts import ensure_virtual_accounts, DEFAULT_VIRTUAL_ACCOUNTS, DEFAULT_VIRTUAL_ACCOUNTS
from trading.strategy.base import Action

LAB_LOG_PATH = Path(__file__).resolve().parents[3] / "state" / "cfd_lab_observations.jsonl"

_GRANULARITY = {"H4": 14400, "H1": 3600, "M15": 900, "M5": 300, "M1": 60}
_COUNT = {"H4": 120, "H1": 160, "M15": 160, "M5": 260, "M1": 300}


def _research_streams():
    for spec in DEFAULT_VIRTUAL_ACCOUNTS:
        if spec.entry_timeframe == "EVENT":
            continue
        tfs = spec.context_timeframes if spec.entry_timeframe in ("MULTI", "TICK") else (spec.entry_timeframe,)
        for tf in tfs:
            if tf in _GRANULARITY:
                yield spec.account_id, tf, _GRANULARITY[tf], _COUNT[tf]


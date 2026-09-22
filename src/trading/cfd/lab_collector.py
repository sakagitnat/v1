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
from trading.cfd.breakout import DonchianBreakoutStrategy
from trading.cfd.mean_reversion import MeanReversionStrategy
from trading.cfd.virtual_accounts import ensure_virtual_accounts, DEFAULT_VIRTUAL_ACCOUNTS
from trading.cfd.paper_trading import run_virtual_account_paper
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
                yield spec, tf


async def collect_lab_observations(broker, instruments, run_id=None):
    """Collect forward-only lab observations and advance PAPER virtual accounts.

    Broker candle access is async. Keep run_id on every observation so forward
    evidence can be attributed to the exact Actions run.
    """
    ensure_virtual_accounts()
    LAB_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    observations = []

    for spec, tf in _research_streams():
        for instrument in instruments:
            try:
                candles = await broker.get_candles(instrument, _GRANULARITY[tf], _COUNT[tf])
                if not candles:
                    continue
                df = pd.DataFrame(candles)
                close = pd.to_numeric(df["close"], errors="coerce").dropna()
                if close.empty:
                    continue
                regime = classify_regime(df)
                volatility = classify_volatility(df)
                strategy = EmaCrossoverStrategy()
                signal = strategy.generate_signal(df)
                breakout = DonchianBreakoutStrategy().generate_signal(df)
                meanrev = MeanReversionStrategy().generate_signal(df)
                obs = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                    "account": spec.account_id,
                    "tier": spec.execution_tier,
                    "strategy": spec.strategy_tag,
                    "timeframe": tf,
                    "instrument": instrument,
                    "regime": regime,
                    "volatility": volatility,
                    "close": float(close.iloc[-1]),
                    "ema_action": signal.action.value if hasattr(signal.action, "value") else str(signal.action),
                    "breakout_action": breakout.action.value if hasattr(breakout.action, "value") else str(breakout.action),
                    "meanrev_action": meanrev.action.value if hasattr(meanrev.action, "value") else str(meanrev.action),
                }
                observations.append(obs)
                with LAB_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(obs, ensure_ascii=False) + "\n")
                if spec.execution_tier == "PAPER" and tf == spec.entry_timeframe:
                    paper_strategy = EmaCrossoverStrategy()
                    run_virtual_account_paper(spec.account_id, instrument, df, regime, paper_strategy)
            except Exception as exc:
                obs = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                    "account": spec.account_id,
                    "timeframe": tf,
                    "instrument": instrument,
                    "error": str(exc),
                }
                observations.append(obs)
                with LAB_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(obs, ensure_ascii=False) + "\n")
    return observations

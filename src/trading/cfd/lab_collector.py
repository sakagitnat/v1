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
from trading.cfd.virtual_accounts import ensure_virtual_accounts
from trading.strategy.base import Action

LAB_LOG_PATH = Path(__file__).resolve().parents[3] / "state" / "cfd_lab_observations.jsonl"

_TIMEFRAMES = {
    "intraday_m15": (900, 160),
    "intraday_m5": (300, 260),
    "scalp_m1": (60, 300),
}


def _signal_payload(instrument: str, bars: pd.DataFrame) -> dict:
    # Research-only baseline, intentionally NOT promoted to an executable strategy.
    # Parameters are the existing EMA form so observations are interpretable; they
    # are not assumed to be valid on lower timeframes.
    strategy = EmaCrossoverStrategy()
    prepared = strategy.prepare(bars)
    row, prev = prepared.iloc[-1], prepared.iloc[-2]
    sig = strategy.signal_for_row(instrument, row, prev, None)
    return {
        "signal_action": sig.action.value if hasattr(sig.action, "value") else str(sig.action),
        "signal_reason": sig.reason,
        "close": float(row["close"]),
        "atr": None if pd.isna(row.get("atr")) else float(row.get("atr")),
        "fast_ema": None if pd.isna(row.get("fast_ema")) else float(row.get("fast_ema")),
        "slow_ema": None if pd.isna(row.get("slow_ema")) else float(row.get("slow_ema")),
    }


async def collect_lab_observations(broker, instruments: list[str], run_id: str | None = None) -> int:
    accounts = ensure_virtual_accounts()
    written = 0
    LAB_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    with LAB_LOG_PATH.open("a") as f:
        for account_id, (granularity, count) in _TIMEFRAMES.items():
            account = accounts[account_id]
            for instrument in instruments:
                try:
                    bars = await broker.get_candles(instrument, granularity_seconds=granularity, count=count)
                    if len(bars) < 50:
                        continue
                    payload = {
                        "timestamp": now,
                        "run_id": run_id,
                        "virtual_account_id": account_id,
                        "execution_tier": account["execution_tier"],
                        "horizon": account["horizon"],
                        "entry_timeframe": account["entry_timeframe"],
                        "context_timeframes": account["context_timeframes"],
                        "instrument": instrument,
                        "bar_time": bars.index[-1].isoformat(),
                        "regime": classify_regime(bars),
                        "volatility": classify_volatility(bars),
                    }
                    payload.update(_signal_payload(instrument, bars))
                    f.write(json.dumps(payload) + "\n")
                    written += 1
                except Exception as exc:
                    f.write(json.dumps({
                        "timestamp": now,
                        "run_id": run_id,
                        "virtual_account_id": account_id,
                        "instrument": instrument,
                        "error": str(exc),
                    }) + "\n")
                    written += 1
    return written

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
from trading.cfd.virtual_accounts import ensure_virtual_accounts, DEFAULT_VIRTUAL_ACCOUNTS\nfrom trading.cfd.paper_trading import run_virtual_account_paper
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



def _strategy_for_tag(strategy_tag: str | None):
    tag = (strategy_tag or "").lower()
    if "breakout" in tag:
        return DonchianBreakoutStrategy()
    if "meanrev" in tag or "mean_reversion" in tag:
        return MeanReversionStrategy()
    return EmaCrossoverStrategy()


def _signal_payload(instrument: str, bars: pd.DataFrame, strategy_tag: str | None) -> dict:
    strategy = _strategy_for_tag(strategy_tag)
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
    streams = list(_research_streams())
    needed = sorted({(tf, gran, count) for _, tf, gran, count in streams}, key=lambda x: x[1], reverse=True)
    cache = {}
    # Fetch each instrument/timeframe once, then fan the same market snapshot
    # out to all virtual accounts. This avoids hammering Deriv ticks_history.
    for instrument in instruments:
        for tf, granularity, count in needed:
            try:
                cache[(instrument, tf)] = await broker.get_candles(
                    instrument, granularity_seconds=granularity, count=count
                )
            except Exception as exc:
                cache[(instrument, tf)] = exc
    with LAB_LOG_PATH.open("a") as fh:
        for account_id, observed_tf, granularity, count in streams:
            account = accounts[account_id]
            for instrument in instruments:
                bars = cache.get((instrument, observed_tf))
                if isinstance(bars, Exception):
                    fh.write(json.dumps({"timestamp": now, "run_id": run_id, "virtual_account_id": account_id, "observed_timeframe": observed_tf, "instrument": instrument, "error": str(bars)}) + "\n")
                    written += 1
                    continue
                if bars is None or len(bars) < 50:
                    continue
                try:
                    payload = {
                        "timestamp": now, "run_id": run_id,
                        "virtual_account_id": account_id,
                        "execution_tier": account["execution_tier"],
                        "horizon": account["horizon"],
                        "entry_timeframe": account["entry_timeframe"],
                        "observed_timeframe": observed_tf,
                        "strategy_tag": account.get("strategy_tag"),
                        "context_timeframes": account["context_timeframes"],
                        "instrument": instrument,
                        "bar_time": bars.index[-1].isoformat(),
                        "regime": classify_regime(bars),
                        "volatility": classify_volatility(bars),
                    }
                    payload.update(_signal_payload(instrument, bars, account.get("strategy_tag")))\n                    # PAPER accounts now consume the same genuine forward candle snapshot.\n                    # Single-timeframe accounts execute only on their entry TF; MULTI accounts\n                    # may maintain independent instrument positions while preserving account attribution.\n                    if account.get("execution_tier") == "PAPER" and (\n                        account.get("entry_timeframe") == observed_tf or account.get("entry_timeframe") == "MULTI"\n                    ):\n                        run_virtual_account_paper(\n                            account_id, instrument, bars, payload["regime"],\n                            _strategy_for_tag(account.get("strategy_tag")),\n                        )
                    fh.write(json.dumps(payload) + "\n")
                    written += 1
                except Exception as exc:
                    fh.write(json.dumps({"timestamp": now, "run_id": run_id, "virtual_account_id": account_id, "observed_timeframe": observed_tf, "instrument": instrument, "error": str(exc)}) + "\n")
                    written += 1
    return written

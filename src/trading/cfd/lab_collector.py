"""Multi-timeframe observation collector for the virtual-account lab.

Forward research only. Candle data is fetched once per (timeframe, instrument)
per run and shared across virtual accounts so the lab cannot exhaust Deriv's
ticks_history quota before the trading scheduler runs.
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


def _append(obs):
    with LAB_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obs, ensure_ascii=False) + "\n")


def _latest_signal(strategy, instrument, bars):
    """Evaluate a strategy through its actual prepare/signal_for_row contract."""
    prepared = strategy.prepare(bars)
    if len(prepared) < 2:
        return None
    return strategy.signal_for_row(instrument, prepared.iloc[-1], prepared.iloc[-2], None)


def _strategy_for_tag(strategy_tag):
    """Use the strategy family encoded in the virtual-account attribution."""
    tag = (strategy_tag or "").lower()
    if "breakout" in tag:
        return DonchianBreakoutStrategy()
    if "meanrev" in tag or "mean_reversion" in tag:
        return MeanReversionStrategy()
    # Trend/control variants currently use the validated EMA implementation.
    return EmaCrossoverStrategy()


async def collect_lab_observations(broker, instruments, run_id=None):
    """Collect forward observations while bounding broker history requests.

    At most one ticks_history request is made for each unique timeframe and
    instrument needed by the lab. Failed fetches are cached too, preventing a
    rate-limit error from causing repeated retries in the same scheduler run.
    """
    ensure_virtual_accounts()
    LAB_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    observations = []
    cache = {}

    streams = list(_research_streams())
    needed = sorted({(tf, instrument) for _, tf in streams for instrument in instruments})
    for tf, instrument in needed:
        try:
            candles = await broker.get_candles(instrument, _GRANULARITY[tf], _COUNT[tf])
            if candles is None:
                cache[(tf, instrument)] = None
            elif isinstance(candles, pd.DataFrame):
                cache[(tf, instrument)] = candles.copy()
            else:
                cache[(tf, instrument)] = pd.DataFrame(candles)
        except Exception as exc:
            cache[(tf, instrument)] = exc

    for spec, tf in streams:
        for instrument in instruments:
            cached = cache.get((tf, instrument))
            try:
                if isinstance(cached, Exception):
                    raise cached
                if cached is None or cached.empty:
                    continue
                df = cached.copy()
                close = pd.to_numeric(df["close"], errors="coerce").dropna()
                if close.empty:
                    continue
                regime = classify_regime(df)
                volatility = classify_volatility(df)
                signal = _latest_signal(EmaCrossoverStrategy(), instrument, df)
                breakout = _latest_signal(DonchianBreakoutStrategy(), instrument, df)
                meanrev = _latest_signal(MeanReversionStrategy(), instrument, df)
                obs = {
                    "timestamp": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
                    "account": spec.account_id, "tier": spec.execution_tier,
                    "strategy": spec.strategy_tag, "timeframe": tf, "instrument": instrument,
                    "regime": regime, "volatility": volatility, "close": float(close.iloc[-1]),
                    "ema_action": (signal.action.value if hasattr(signal.action, "value") else str(signal.action)) if signal else "hold",
                    "breakout_action": (breakout.action.value if hasattr(breakout.action, "value") else str(breakout.action)) if breakout else "hold",
                    "meanrev_action": (meanrev.action.value if hasattr(meanrev.action, "value") else str(meanrev.action)) if meanrev else "hold",
                }
                observations.append(obs)
                _append(obs)
                if spec.execution_tier == "PAPER" and tf == spec.entry_timeframe:
                    run_virtual_account_paper(spec.account_id, instrument, df, regime, _strategy_for_tag(spec.strategy_tag))
            except Exception as exc:
                obs = {"timestamp": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
                       "account": spec.account_id, "timeframe": tf, "instrument": instrument,
                       "error": str(exc)}
                observations.append(obs)
                _append(obs)
    return observations

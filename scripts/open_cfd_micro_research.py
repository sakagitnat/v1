"""Aggressive DEMO-only micro-horizon research executor.

Opens at most one M1 probe and one tick-seconds probe, each tracked in its
own virtual $100 ledger. These are explicitly experimental and never treated
as validated strategies. Master exposure is still bounded by a small fixed
research-risk budget.
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker
from trading.cfd.state import list_open_trades, record_open_trade
from trading.config import settings
from trading.indicators import ema

INSTRUMENTS = ["frxXAUUSD","frxEURUSD","frxGBPUSD","frxUSDJPY"]
MAX_TOTAL_RESEARCH_RISK = 1.50
MICRO_LOG = Path(__file__).resolve().parents[1] / "state" / "cfd_micro_observations.jsonl"

def _log(row):
    MICRO_LOG.parent.mkdir(parents=True, exist_ok=True)
    with MICRO_LOG.open("a") as f:
        f.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), **row}) + "\n")

STAKE = 1.00
STOP = 0.25
TARGET = 0.50
MULTIPLIER = 100

def _m1_signal(df):
    if len(df) < 60: return None
    fast, slow = ema(df["close"], 9), ema(df["close"], 21)
    mom = df["close"].iloc[-1] - df["close"].iloc[-3]
    if fast.iloc[-1] > slow.iloc[-1] and mom > 0: return "long"
    if fast.iloc[-1] < slow.iloc[-1] and mom < 0: return "short"
    return None

def _tick_signal(ticks):
    if len(ticks) < 40: return None
    s=ticks["price"].astype(float)
    short=s.rolling(8).mean()
    long=s.rolling(30).mean()
    impulse=s.iloc[-1]-s.iloc[-8]
    if short.iloc[-1] > long.iloc[-1] and impulse > 0: return "long"
    if short.iloc[-1] < long.iloc[-1] and impulse < 0: return "short"
    return None

async def _open(broker, symbol, side, strategy, account_id, timeframe, reason, entry_price):
    result=await broker.submit_multiplier_order(symbol,side,STAKE,MULTIPLIER,STOP,TARGET)
    cid=result.get("buy",{}).get("contract_id")
    if cid is None: raise RuntimeError(f"no contract_id: {result!r}")
    record_open_trade(cid,{
        "instrument":symbol,"strategy":strategy,"side":side,
        "entry_time":datetime.now(timezone.utc).isoformat(),"entry_price":entry_price,
        "stake":STAKE,"risk_amount":STOP,"multiplier":MULTIPLIER,
        "thesis_key":f"{symbol}:{side}:{strategy}",
        "equity_before":100.0,"regime":"micro_research","leg":"scalp",
        "broker_managed_only":True,"entry_reason":reason,"experimental":True,
        "virtual_account_id":account_id,"horizon":"scalp",
        "entry_timeframe":timeframe,"context_timeframes":["M5","M1",timeframe],
    })
    print(f"OPENED {strategy} {symbol} {side} contract_id={cid}")

async def main():
    if settings.cfd_allow_live_trading:
        raise SystemExit("Refusing while CFD_ALLOW_LIVE_TRADING=true")
    broker=DerivBroker()
    try:
        account=await broker.connect()
        if account.get("account_type")!="demo": raise SystemExit("demo account required")
        tracked=list_open_trades()
        total_risk=sum(float(x.get("risk_amount",0)) for x in tracked.values())
        existing={x.get("strategy") for x in tracked.values()}
        if total_risk >= MAX_TOTAL_RESEARCH_RISK:
            print(f"NO_NEW_MICRO: research risk already {total_risk:.2f}")
            return

        if "starter_m1@v0" not in existing and total_risk + STOP <= MAX_TOTAL_RESEARCH_RISK:
            candidates=[]
            for sym in INSTRUMENTS:
                m5=await broker.get_candles(sym,300,100)
                m1=await broker.get_candles(sym,60,120)
                side=_m1_signal(m1)
                if side:
                    strength=abs(float(ema(m1["close"],9).iloc[-1]-ema(m1["close"],21).iloc[-1]))/max(abs(float(m1["close"].iloc[-1])),1e-9)
                    m5bias="long" if ema(m5["close"],9).iloc[-1] > ema(m5["close"],21).iloc[-1] else "short"
                    bonus=1 if side==m5bias else 0
                    candidates.append((bonus+strength,sym,side,float(m1["close"].iloc[-1])))
            _log({"account":"scalp_m1","timeframe":"M1","candidate_count":len(candidates),"existing_risk":total_risk})
            if candidates:
                _,sym,side,price=max(candidates)
                _log({"account":"scalp_m1","timeframe":"M1","instrument":sym,"signal":side,"price":price,"selected":True})
                await _open(broker,sym,side,"starter_m1@v0","scalp_m1","M1","M1 EMA9/21 + 3-bar momentum, ranked with M5 bias",price)
                total_risk += STOP

        if "starter_ticks@v0" not in existing and total_risk + STOP <= MAX_TOTAL_RESEARCH_RISK:
            candidates=[]
            for sym in INSTRUMENTS:
                ticks=await broker.get_ticks(sym,300)
                side=_tick_signal(ticks)
                if side:
                    px=float(ticks["price"].iloc[-1])
                    impulse=abs(px-float(ticks["price"].iloc[-8]))/max(abs(px),1e-9)
                    candidates.append((impulse,sym,side,px))
            _log({"account":"scalp_ticks","timeframe":"TICK","candidate_count":len(candidates),"existing_risk":total_risk})
            if candidates:
                _,sym,side,price=max(candidates)
                _log({"account":"scalp_ticks","timeframe":"TICK","instrument":sym,"signal":side,"price":price,"selected":True})
                await _open(broker,sym,side,"starter_ticks@v0","scalp_ticks","TICK","8-tick vs 30-tick mean + 8-tick impulse",price)
    finally:
        await broker.close()

if __name__=="__main__":
    asyncio.run(main())

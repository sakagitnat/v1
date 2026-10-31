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
import os
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker
from trading.cfd.state import list_open_trades, record_open_trade, pop_open_trade
from trading.cfd.virtual_accounts import ensure_virtual_accounts, record_virtual_close
from trading.config import settings
from trading.indicators import ema
from trading.cfd.trade_log import TradeRecord, record_trade

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
CONTINUOUS_SECONDS = int(os.getenv("CFD_MICRO_CONTINUOUS_SECONDS", "0"))
TICK_CYCLE_SECONDS = 1650
MINUTE_CYCLE_SECONDS = 3300

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


async def _quota_cycle(broker, timeframe, cycle_no):
    """DEMO-only forced research cycle. Kept explicitly separate from qualified signals."""
    is_tick = timeframe == "TICK"
    strategy = "quota_30m@v0" if is_tick else "quota_h1@v0"
    account_id = "quota_30m_forward" if is_tick else "quota_h1_forward"
    symbol = INSTRUMENTS[cycle_no % len(INSTRUMENTS)]
    if is_tick:
        data = await broker.get_ticks(symbol, 80)
        if data.empty: return
        price = float(data["price"].iloc[-1])
        side = _tick_signal(data) or ("long" if float(data["price"].iloc[-1]) >= float(data["price"].iloc[-2]) else "short")
    else:
        data = await broker.get_candles(symbol, 60, 80)
        if data.empty: return
        price = float(data["close"].iloc[-1])
        side = _m1_signal(data) or ("long" if float(data["close"].iloc[-1]) >= float(data["close"].iloc[-2]) else "short")
    result = await broker.submit_multiplier_order(symbol, side, STAKE, MULTIPLIER, STOP, TARGET)
    cid = result.get("buy", {}).get("contract_id")
    if cid is None:
        _log({"event":"quota_open_failed","timeframe":timeframe,"instrument":symbol,"result":result})
        return
    opened = datetime.now(timezone.utc)
    meta={"instrument":symbol,"strategy":strategy,"side":side,"entry_time":opened.isoformat(),
          "entry_price":price,"stake":STAKE,"risk_amount":STOP,"multiplier":MULTIPLIER,
          "equity_before":100.0,"regime":"forced_quota_research","leg":"quota",
          "broker_managed_only":False,"entry_reason":"research quota; not strategy-qualified",
          "experimental":True,"forced_quota":True,"virtual_account_id":account_id,
          "horizon":"30m" if is_tick else "h1","entry_timeframe":timeframe,
          "context_timeframes":[timeframe]}
    record_open_trade(cid, meta)
    # Give Deriv at least one price tick before attempting an explicit sell.
    await asyncio.sleep(8 if is_tick else 20)
    try:
        sold = await broker.close_position(int(cid))
        sell = sold.get("sell", {})
        # Deriv's newer sell response may omit "profit". The sell_price is
        # the actual cash returned on close; for a multiplier bought on a
        # stake basis, realized P&L is sell_price - original stake.
        # Never persist a closed quota trade with unknown P&L.
        raw_profit = sell.get("profit")
        raw_sell_price = sell.get("sell_price")
        if raw_profit is not None:
            pnl = float(raw_profit)
        elif raw_sell_price is not None:
            pnl = float(raw_sell_price) - STAKE
        else:
            raise RuntimeError(f"sell response missing both profit and sell_price: {sold!r}")
        exit_price = None if raw_sell_price is None else float(raw_sell_price)
        pop_open_trade(int(cid))
        try:
            record_virtual_close(account_id, pnl)
        except KeyError:
            # Quota accounts are intentionally separate forward ledgers.
            # Seed them in virtual_accounts.py; unknown attribution is an
            # error rather than silently dropping realized P&L.
            raise RuntimeError(f"unknown quota virtual account: {account_id}")
        record_trade(TradeRecord(contract_id=int(cid),instrument=symbol,strategy=strategy,side=side,
            entry_time=opened.isoformat(),exit_time=datetime.now(timezone.utc).isoformat(),
            entry_price=price,stake=STAKE,risk_amount=STOP,exit_price=exit_price,pnl=pnl,
            equity_before=100.0,equity_after=None,exit_reason="forced_quota_cycle",
            regime="forced_quota_research",leg="quota",virtual_account_id=account_id,
            horizon="seconds" if is_tick else "minute",entry_timeframe=timeframe,
            context_timeframes=[timeframe]))
        _log({"event":"quota_cycle_closed","timeframe":timeframe,"account":account_id,
              "instrument":symbol,"side":side,"contract_id":cid,"pnl":pnl,"forced_quota":True})
    except Exception as exc:
        _log({"event":"quota_close_error","timeframe":timeframe,"account":account_id,
              "instrument":symbol,"contract_id":cid,"error":repr(exc),"forced_quota":True})


async def continuous_quota_loop():
    """Run inside one Actions job: 30-minute and hourly DEMO research quotas."""
    if settings.cfd_allow_live_trading:
        raise SystemExit("Refusing while CFD_ALLOW_LIVE_TRADING=true")
    broker=DerivBroker()
    try:
        account=await broker.connect()
        if account.get("account_type")!="demo": raise SystemExit("demo account required")
        started=time.monotonic(); tick_n=0; m1_n=0; next_tick=started; next_m1=started
        while time.monotonic()-started < CONTINUOUS_SECONDS:
            now=time.monotonic()
            if now >= next_tick:
                try: await _quota_cycle(broker,"TICK",tick_n)
                except Exception as exc: _log({"event":"tick_cycle_error","error":repr(exc)})
                tick_n += 1; next_tick = max(next_tick + TICK_CYCLE_SECONDS, time.monotonic())
            if now >= next_m1:
                try: await _quota_cycle(broker,"M1",m1_n)
                except Exception as exc: _log({"event":"m1_cycle_error","error":repr(exc)})
                m1_n += 1; next_m1 = max(next_m1 + MINUTE_CYCLE_SECONDS, time.monotonic())
            await asyncio.sleep(1)
    finally:
        await broker.close()

async def main():
    if settings.cfd_allow_live_trading:
        raise SystemExit("Refusing while CFD_ALLOW_LIVE_TRADING=true")
    ensure_virtual_accounts()
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
    if CONTINUOUS_SECONDS > 0:
        asyncio.run(continuous_quota_loop())
    else:
        asyncio.run(main())

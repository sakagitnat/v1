"""High-risk DEMO-only growth experiment.

Goal: test whether aggressive virtual-$100 variants can reach $200 quickly.
This is not a claim of expected profitability. Each account is isolated in
analytics, while broker-level exposure is capped so one failed experiment
cannot consume the whole $10k demo account.
"""
import asyncio, json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker
from trading.cfd.state import list_open_trades, record_open_trade
from trading.cfd.virtual_accounts import ensure_virtual_accounts
from trading.config import settings
from trading.indicators import ema

INSTRUMENTS=["frxXAUUSD","frxEURUSD","frxGBPUSD","frxUSDJPY"]
LOG=Path(__file__).resolve().parents[1]/"state"/"cfd_highrisk_observations.jsonl"
BROKER_RESEARCH_RISK_CAP=25.0   # dollars of configured stop risk across experimental positions
STAKE=10.0
STOP=8.0                       # 8% of a virtual $100 sub-account per trade
TARGET=12.0                    # 1.5R target
MULTIPLIER=100

def log(row):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"timestamp":datetime.now(timezone.utc).isoformat(),**row})+"\n")

def m1_candidate(m15,m5,m1):
    if min(len(m15),len(m5),len(m1))<60:return None
    def bias(df,a,b): return 1 if ema(df["close"],a).iloc[-1]>ema(df["close"],b).iloc[-1] else -1
    votes=[bias(m15,9,21),bias(m5,9,21),bias(m1,9,21)]
    mom=1 if m1["close"].iloc[-1]>m1["close"].iloc[-4] else -1
    score=sum(votes)
    if abs(score)>=1 and (score>0)==(mom>0):
        side="long" if score>0 else "short"
        strength=abs(float(ema(m1["close"],9).iloc[-1]-ema(m1["close"],21).iloc[-1]))/max(abs(float(m1["close"].iloc[-1])),1e-9)
        return side,abs(score)+strength,votes,float(m1["close"].iloc[-1])
    return None

def tick_candidate(ticks):
    if len(ticks)<80:return None
    s=ticks["price"].astype(float)
    a=s.rolling(6).mean().iloc[-1]; b=s.rolling(24).mean().iloc[-1]; c=s.rolling(60).mean().iloc[-1]
    impulse=float(s.iloc[-1]-s.iloc[-12])
    if a>b>c and impulse>0:return "long",abs(impulse)/max(abs(float(s.iloc[-1])),1e-9),float(s.iloc[-1])
    if a<b<c and impulse<0:return "short",abs(impulse)/max(abs(float(s.iloc[-1])),1e-9),float(s.iloc[-1])
    return None

async def open_trade(broker,symbol,side,strategy,account_id,timeframe,reason,price):
    result=await broker.submit_multiplier_order(symbol,side,STAKE,MULTIPLIER,STOP,TARGET)
    cid=result.get("buy",{}).get("contract_id")
    if cid is None: raise RuntimeError(f"no contract_id: {result!r}")
    record_open_trade(cid,{
      "instrument":symbol,"strategy":strategy,"side":side,
      "entry_time":datetime.now(timezone.utc).isoformat(),"entry_price":price,
      "stake":STAKE,"risk_amount":STOP,"multiplier":MULTIPLIER,
      "thesis_key":f"{symbol}:{side}:{strategy}","equity_before":100.0,
      "regime":"highrisk_growth_experiment","leg":"aggressive",
      "broker_managed_only":True,"entry_reason":reason,"experimental":True,
      "high_risk":True,"virtual_account_id":account_id,"horizon":"highrisk",
      "entry_timeframe":timeframe,"context_timeframes":["M15","M5","M1",timeframe]
    })
    log({"event":"trade_opened","account":account_id,"strategy":strategy,"instrument":symbol,"side":side,"risk":STOP,"target":TARGET,"contract_id":cid,"reason":reason})
    print(f"OPENED {account_id} {symbol} {side} risk={STOP}")

async def main():
    if settings.cfd_allow_live_trading: raise SystemExit("CFD_ALLOW_LIVE_TRADING must remain false")
    ensure_virtual_accounts()
    broker=DerivBroker()
    try:
        acct=await broker.connect()
        if acct.get("account_type")!="demo": raise SystemExit("demo account required")
        tracked=list_open_trades()
        total_risk=sum(float(x.get("risk_amount",0)) for x in tracked.values())
        existing={x.get("strategy") for x in tracked.values()}
        log({"event":"scan_start","tracked_risk":total_risk,"open_count":len(tracked)})
        if total_risk+STOP > BROKER_RESEARCH_RISK_CAP:
            log({"event":"blocked","reason":"broker research risk cap","tracked_risk":total_risk})
            return

        if "highrisk_m1@v0" not in existing:
            cs=[]
            for sym in INSTRUMENTS:
                m15=await broker.get_candles(sym,900,120); m5=await broker.get_candles(sym,300,160); m1=await broker.get_candles(sym,60,180)
                x=m1_candidate(m15,m5,m1)
                log({"event":"candidate","account":"highrisk_m1","instrument":sym,"candidate":None if x is None else {"side":x[0],"score":x[1],"votes":x[2],"price":x[3]}})
                if x: cs.append((x[1],sym,x))
            if cs:
                _,sym,x=max(cs); side,score,votes,price=x
                await open_trade(broker,sym,side,"highrisk_m1@v0","highrisk_m1","M1",f"M15/M5/M1 vote={votes}, M1 momentum confirmed; score={score:.6f}",price)
                total_risk+=STOP

        if "highrisk_ticks@v0" not in existing and total_risk+STOP <= BROKER_RESEARCH_RISK_CAP:
            cs=[]
            for sym in INSTRUMENTS:
                ticks=await broker.get_ticks(sym,500)
                x=tick_candidate(ticks)
                log({"event":"candidate","account":"highrisk_ticks","instrument":sym,"candidate":None if x is None else {"side":x[0],"score":x[1],"price":x[2]}})
                if x: cs.append((x[1],sym,x))
            if cs:
                _,sym,x=max(cs); side,score,price=x
                await open_trade(broker,sym,side,"highrisk_ticks@v0","highrisk_ticks","TICK",f"6/24/60-tick trend stack + 12-tick impulse; score={score:.8f}",price)
    finally:
        await broker.close()

if __name__=="__main__":
    asyncio.run(main())

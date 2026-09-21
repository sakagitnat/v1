"""Open one small DEMO short-horizon trade from multi-timeframe alignment.

DEMO only; requires no existing position. H1 sets bias, M15 confirms, M5 triggers.
Uses a $1 stake with $0.50 stop and $1.00 target. Deriv manages SL/TP.
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker
from trading.cfd.state import list_open_trades, record_open_trade
from trading.config import settings
from trading.indicators import ema

INSTRUMENTS = ["frxXAUUSD", "frxEURUSD", "frxGBPUSD", "frxUSDJPY"]

def _signal(h1, m15, m5):
    if min(len(h1), len(m15), len(m5)) < 60:
        return None
    h1_fast, h1_slow = ema(h1["close"], 20), ema(h1["close"], 50)
    m15_fast, m15_slow = ema(m15["close"], 9), ema(m15["close"], 21)
    m5_fast, m5_slow = ema(m5["close"], 9), ema(m5["close"], 21)
    bullish = h1_fast.iloc[-1] > h1_slow.iloc[-1] and m15_fast.iloc[-1] > m15_slow.iloc[-1]
    bearish = h1_fast.iloc[-1] < h1_slow.iloc[-1] and m15_fast.iloc[-1] < m15_slow.iloc[-1]
    crossed_up = m5_fast.iloc[-2] <= m5_slow.iloc[-2] and m5_fast.iloc[-1] > m5_slow.iloc[-1]
    crossed_down = m5_fast.iloc[-2] >= m5_slow.iloc[-2] and m5_fast.iloc[-1] < m5_slow.iloc[-1]
    reclaim_up = bullish and m5["close"].iloc[-2] <= m5_fast.iloc[-2] and m5["close"].iloc[-1] > m5_fast.iloc[-1]
    reclaim_down = bearish and m5["close"].iloc[-2] >= m5_fast.iloc[-2] and m5["close"].iloc[-1] < m5_fast.iloc[-1]
    if bullish and (crossed_up or reclaim_up):
        return "long", "H1+M15 bullish; M5 crossover/reclaim"
    if bearish and (crossed_down or reclaim_down):
        return "short", "H1+M15 bearish; M5 crossover/rejection"
    return None

async def main():
    if settings.cfd_allow_live_trading:
        raise SystemExit("Refusing while CFD_ALLOW_LIVE_TRADING=true")
    if list_open_trades():
        raise SystemExit("Refusing: local open trade already exists")
    broker = DerivBroker()
    try:
        account = await broker.connect()
        if account.get("account_type") != "demo":
            raise SystemExit("Refusing: connected account is not demo")
        broker_positions = await broker.open_positions_list()
        if broker_positions:
            raise SystemExit(f"Refusing: {len(broker_positions)} broker position(s) already open")
        candidates = []
        for symbol in INSTRUMENTS:
            h1 = await broker.get_candles(symbol, granularity_seconds=3600, count=120)
            m15 = await broker.get_candles(symbol, granularity_seconds=900, count=160)
            m5 = await broker.get_candles(symbol, granularity_seconds=300, count=220)
            sig = _signal(h1, m15, m5)
            if sig:
                side, reason = sig
                f = ema(m5["close"], 9).iloc[-1]
                s = ema(m5["close"], 21).iloc[-1]
                strength = abs(f - s) / max(abs(m5["close"].iloc[-1]), 1e-9)
                candidates.append((strength, symbol, side, reason, float(m5["close"].iloc[-1])))
        if not candidates:
            print("NO_TRADE: no H1+M15 aligned M5 setup right now")
            return
        candidates.sort(reverse=True)
        _, symbol, side, reason, entry_price = candidates[0]
        stake, stop_loss_amount, take_profit_amount, multiplier = 1.00, 0.50, 1.00, 20
        print(f"STARTER_INTRADAY {symbol} {side}; {reason}; stake={stake:.2f} stop={stop_loss_amount:.2f} target={take_profit_amount:.2f}")
        result = await broker.submit_multiplier_order(symbol, side, stake, multiplier, stop_loss_amount, take_profit_amount)
        contract_id = result.get("buy", {}).get("contract_id")
        if contract_id is None:
            raise RuntimeError(f"Order returned no contract_id: {result!r}")
        record_open_trade(contract_id, {
            "instrument": symbol, "strategy": "starter_intraday@v0", "side": side,
            "entry_time": datetime.now(timezone.utc).isoformat(), "entry_price": entry_price,
            "stake": stake, "risk_amount": stop_loss_amount, "multiplier": multiplier,
            "thesis_key": f"{symbol}:{side}:starter_intraday",
            "equity_before": settings.cfd_virtual_starting_capital,
            "regime": "short_horizon_probe", "leg": "scalp", "broker_managed_only": True,
            "entry_reason": reason, "timeframes": ["H1", "M15", "M5"]
        })
        print(f"TRADE_OPENED contract_id={contract_id} {symbol} {side}")
    finally:
        await broker.close()

if __name__ == "__main__":
    asyncio.run(main())

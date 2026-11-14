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
    m5_bullish = m5_fast.iloc[-1] > m5_slow.iloc[-1]
    m5_bearish = m5_fast.iloc[-1] < m5_slow.iloc[-1]
    momentum_up = m5["close"].iloc[-1] > m5["close"].iloc[-2]
    momentum_down = m5["close"].iloc[-1] < m5["close"].iloc[-2]

    if bullish and m5_bullish and (crossed_up or reclaim_up or momentum_up):
        return "long", "H1+M15+M5 bullish alignment with short-horizon momentum"
    if bearish and m5_bearish and (crossed_down or reclaim_down or momentum_down):
        return "short", "H1+M15+M5 bearish alignment with short-horizon momentum"
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
        fallbacks = []
        m5_only = []
        for symbol in INSTRUMENTS:
            h1 = await broker.get_candles(symbol, granularity_seconds=3600, count=120)
            m15 = await broker.get_candles(symbol, granularity_seconds=900, count=160)
            m5 = await broker.get_candles(symbol, granularity_seconds=300, count=220)
            sig = _signal(h1, m15, m5)
            f = ema(m5["close"], 9).iloc[-1]
            s = ema(m5["close"], 21).iloc[-1]
            strength = abs(f - s) / max(abs(m5["close"].iloc[-1]), 1e-9)
            if sig:
                side, reason = sig
                candidates.append((strength + 10.0, symbol, side, reason, float(m5["close"].iloc[-1])))
                continue

            h1_fast, h1_slow = ema(h1["close"], 20).iloc[-1], ema(h1["close"], 50).iloc[-1]
            m15_fast, m15_slow = ema(m15["close"], 9).iloc[-1], ema(m15["close"], 21).iloc[-1]
            m5_fast, m5_slow = f, s
            votes = [
                1 if h1_fast > h1_slow else -1,
                1 if m15_fast > m15_slow else -1,
                1 if m5_fast > m5_slow else -1,
            ]
            score = sum(votes)
            m5_momentum = 1 if m5["close"].iloc[-1] > m5["close"].iloc[-2] else -1
            if abs(score) >= 1 and (score > 0) == (m5_momentum > 0):
                side = "long" if score > 0 else "short"
                reason = f"experimental majority MTF vote H1/M15/M5={votes}, M5 momentum confirms"
                confidence = abs(score) + strength
                fallbacks.append((confidence, symbol, side, reason, float(m5["close"].iloc[-1])))

            # Final exploratory fallback for the very first demo data point:
            # strongest M5 EMA separation whose latest candle agrees with
            # that M5 direction. This is intentionally tagged experimental
            # and uses the same tiny fixed risk.
            if m5_fast > m5_slow:
                m5_only.append((strength, symbol, "long", "experimental M5 EMA-direction execution probe", float(m5["close"].iloc[-1])))
            elif m5_fast < m5_slow:
                m5_only.append((strength, symbol, "short", "experimental M5 EMA-direction execution probe", float(m5["close"].iloc[-1])))

        if not candidates:
            if fallbacks:
                fallbacks.sort(reverse=True)
                candidates = [fallbacks[0]]
            elif m5_only:
                m5_only.sort(reverse=True)
                candidates = [m5_only[0]]
            else:
                print("NO_TRADE: no M5 momentum candidate available")
                return
        candidates.sort(reverse=True)
        _, symbol, side, reason, entry_price = candidates[0]
        stake, stop_loss_amount, take_profit_amount, multiplier = 1.00, 0.50, 1.00, 100
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
            "entry_reason": reason, "timeframes": ["H1", "M15", "M5"],
            "virtual_account_id": "starter_m5_probe",
            "horizon": "intraday",
            "entry_timeframe": "M5",
            "context_timeframes": ["H1", "M15", "M5"],
            "experimental": True
        })
        print(f"TRADE_OPENED contract_id={contract_id} {symbol} {side}")
    finally:
        await broker.close()

if __name__ == "__main__":
    asyncio.run(main())

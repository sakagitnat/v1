"""AI-supervisor helpers for DailyPlanExecutor.

    python scripts/mt5_daily_plan.py snapshot [SYMBOL ...]
        Prints candles + indicators (D1/H1/M15) and key levels so the daily
        plan can be decided from the chart.
    python scripts/mt5_daily_plan.py write SYMBOL BUY|SELL --sl P --tp P
            [--trigger P --dir ABOVE|BELOW] [--start 10] [--force 19]
            [--risk 5] --reason "text"
        Validates and writes plan_<SYMBOL>.txt into the MT5 Common\\Files
        folder (dated with the broker's server date).
"""
import argparse
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

DEFAULT_SYMBOLS = ["GER40Cash", "US500Cash", "US100Cash", "GOLD"]


def _mt5():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise SystemExit(f"MT5 not reachable ({mt5.last_error()})")
    return mt5


def _rates(mt5, sym, tf, n):
    r = mt5.copy_rates_from_pos(sym, tf, 0, n)
    if r is None or len(r) == 0:
        return None
    df = pd.DataFrame(r)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def _ind(df):
    c, h, l = df["close"], df["high"], df["low"]
    df["ema20"] = c.ewm(span=20, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return df


def snapshot(symbols):
    mt5 = _mt5()
    try:
        tick0 = mt5.symbol_info_tick(symbols[0])
        print("server time (last tick):", dt.datetime.fromtimestamp(tick0.time, dt.timezone.utc) if tick0 else "n/a")
        for sym in symbols:
            if not mt5.symbol_select(sym, True):
                print(f"\n== {sym}: not available =="); continue
            info, tick = mt5.symbol_info(sym), mt5.symbol_info_tick(sym)
            print(f"\n== {sym} ==  bid {tick.bid} ask {tick.ask}  spread {info.spread}pts  min lot {info.volume_min}  stops_level {info.trade_stops_level}")
            for name, tf, n, show in (("D1", mt5.TIMEFRAME_D1, 120, 6), ("H1", mt5.TIMEFRAME_H1, 200, 8), ("M15", mt5.TIMEFRAME_M15, 200, 8)):
                df = _rates(mt5, sym, tf, n)
                if df is None: continue
                df = _ind(df); dg = info.digits
                last = df.iloc[-1]
                trend = "UP" if last.ema20 > last.ema50 else "DOWN"
                print(f"-- {name}: close {last.close:.{dg}f} ema20 {last.ema20:.{dg}f} ema50 {last.ema50:.{dg}f} ({trend}) rsi {last.rsi:.0f} atr {last.atr:.{dg}f}")
                print(df.tail(show)[["time", "open", "high", "low", "close"]].to_string(index=False, float_format=lambda x: f"{x:.{dg}f}"))
                if name == "D1":
                    prev = df.iloc[-2]
                    print(f"   prev day H {prev.high:.{dg}f} L {prev.low:.{dg}f} C {prev.close:.{dg}f} | 20d high {df.high.tail(20).max():.{dg}f} low {df.low.tail(20).min():.{dg}f}")
    finally:
        mt5.shutdown()


def common_files():
    return os.path.join(os.environ["APPDATA"], "MetaQuotes", "Terminal", "Common", "Files")


def write_plan(a):
    mt5 = _mt5()
    try:
        sym = a.symbol
        mt5.symbol_select(sym, True)
        tick, info = mt5.symbol_info_tick(sym), mt5.symbol_info(sym)
        if tick is None or info is None:
            raise SystemExit(f"no quote for {sym}")
        buy = a.side == "BUY"
        px = tick.ask if buy else tick.bid
        risk_pts = (px - a.sl) if buy else (a.sl - px)
        if risk_pts <= 0:
            raise SystemExit(f"SL {a.sl} is on the wrong side of price {px}")
        if a.tp and ((buy and a.tp <= px) or (not buy and a.tp >= px)):
            raise SystemExit(f"TP {a.tp} is on the wrong side of price {px}")
        if a.risk > 10:
            raise SystemExit("risk above $10 per trade is not allowed")
        server_date = dt.datetime.fromtimestamp(tick.time, dt.timezone.utc).strftime("%Y.%m.%d")
        lines = [f"date={server_date}", f"side={a.side}", f"sl={a.sl}", f"tp={a.tp or 0}",
                 f"trigger={a.trigger or 0}", f"trigger_dir={a.dir}", f"start_hour={a.start}",
                 f"force_hour={a.force}", f"risk={a.risk}", f"reason={a.reason}"]
        folder = common_files()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"plan_{sym}.txt")
        with open(path, "w", encoding="ascii", errors="replace") as f:
            f.write("\n".join(lines) + "\n")
        print(f"wrote {path}\n  price {px}  stop distance {risk_pts:.2f}  date {server_date}")
    finally:
        mt5.shutdown()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("symbols", nargs="*")
    w = sub.add_parser("write")
    w.add_argument("symbol"); w.add_argument("side", choices=["BUY", "SELL"])
    w.add_argument("--sl", type=float, required=True); w.add_argument("--tp", type=float, default=0)
    w.add_argument("--trigger", type=float, default=0); w.add_argument("--dir", default="ABOVE", choices=["ABOVE", "BELOW"])
    w.add_argument("--start", type=int, default=10); w.add_argument("--force", type=int, default=19)
    w.add_argument("--risk", type=float, default=5.0); w.add_argument("--reason", required=True)
    a = ap.parse_args()
    if a.cmd == "snapshot":
        snapshot(a.symbols or DEFAULT_SYMBOLS)
    else:
        write_plan(a)


if __name__ == "__main__":
    sys.exit(main())

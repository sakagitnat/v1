"""Trade review for the MT5 demo account: reads closed deals straight from the
MT5 terminal (history_deals_get), groups them by EA magic number and prints
win rate / profit factor / expectancy / drawdown plus a data-driven verdict.

Run on the Windows PC with the MT5 terminal open and logged in:
    python scripts/mt5_review.py [--since 2026-11-04]

Verdict rules (deliberately simple, so a review never over-reacts to luck):
  - fewer than MIN_TRADES closed trades -> "keep collecting", no conclusion
  - profit factor below PAUSE_PF, or drawdown above PAUSE_DD_PCT of the
    starting balance -> "pause and review"
  - otherwise -> "on track" (or "ahead of backtest" when it beats it)
"""
import argparse
import datetime as dt

import pandas as pd

# EA magic -> (name, backtest profit factor, backtest win rate %)
EAS = {
    20261104: ("MeanReversionDay (retired)", None, None),
    20261105: ("GoldTrendH1", 1.05, None),
    20261106: ("IndexOrbDay", 1.31, 45),
}
MIN_TRADES = 30
PAUSE_PF = 0.8
PAUSE_DD_PCT = 40.0


def _verdict(n, pf, dd_pct, bt_pf):
    if n < MIN_TRADES:
        return f"keep collecting ({n}/{MIN_TRADES} trades) -- too few to conclude anything"
    if pf < PAUSE_PF or dd_pct > PAUSE_DD_PCT:
        return "PAUSE and review: profit factor or drawdown is outside the acceptable range"
    if bt_pf and pf >= bt_pf:
        return "ahead of / in line with the backtest"
    return "on track (within range, below backtest)"


def _stats(g, start_balance):
    pnl = g["net"].values
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    gp, gl = wins.sum(), -losses.sum()
    equity = start_balance + pnl.cumsum()
    peak = pd.Series(equity).cummax().values
    dd_pct = float(((peak - equity) / peak).max() * 100) if len(pnl) else 0.0
    return dict(
        n=len(pnl),
        win=100 * len(wins) / len(pnl) if len(pnl) else 0.0,
        net=pnl.sum(),
        pf=gp / gl if gl else (9.99 if gp else 0.0),
        exp=pnl.mean() if len(pnl) else 0.0,
        avg_win=wins.mean() if len(wins) else 0.0,
        avg_loss=losses.mean() if len(losses) else 0.0,
        dd_pct=dd_pct,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-11-04", help="YYYY-MM-DD, first day to include")
    args = ap.parse_args()

    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise SystemExit(f"MT5 not reachable ({mt5.last_error()}) -- open the terminal and log in first.")
    try:
        acct = mt5.account_info()
        start = dt.datetime.fromisoformat(args.since)
        deals = mt5.history_deals_get(start, dt.datetime.now() + dt.timedelta(days=2)) or ()
        print(f"Account {acct.login}: balance {acct.balance:.2f}  equity {acct.equity:.2f}  open P&L {acct.profit:.2f}")
        open_pos = mt5.positions_get() or ()
        print(f"Open positions: {len(open_pos)}")
        df = pd.DataFrame([d._asdict() for d in deals])
        if df.empty:
            print(f"No deals since {args.since} -- nothing to analyse yet.")
            return
        # Closing deals carry the realised result; costs sit on the same deal.
        out = df[df["entry"] == mt5.DEAL_ENTRY_OUT].copy()
        out["net"] = out["profit"] + out["commission"] + out["swap"]
        out["time"] = pd.to_datetime(out["time"], unit="s")
        start_balance = acct.balance - out["net"].sum()
        for magic, g in out.sort_values("time").groupby("magic"):
            name, bt_pf, _ = EAS.get(int(magic), (f"magic {magic}", None, None))
            s = _stats(g, start_balance)
            print(f"\n== {name} ==  closed trades {s['n']}")
            print(f"  win rate {s['win']:.0f}%  net {s['net']:+.2f}  profit factor {s['pf']:.2f}"
                  + (f" (backtest {bt_pf})" if bt_pf else ""))
            print(f"  expectancy {s['exp']:+.2f}/trade  avg win {s['avg_win']:+.2f}  avg loss {s['avg_loss']:+.2f}  max drawdown {s['dd_pct']:.0f}%")
            print(f"  verdict: {_verdict(s['n'], s['pf'], s['dd_pct'], bt_pf)}")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()

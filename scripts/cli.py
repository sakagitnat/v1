"""Manual control for the trading bot: status, pause/resume, capital floor,
and one-off orders.

Meant to be run by the "Manual Trading Command" GitHub Actions workflow
(workflow_dispatch), which Claude triggers on your behalf when you ask for
something in chat -- it never needs your Alpaca keys directly, since those
live only in the repository's GitHub Actions secrets.

Usage:
  python scripts/cli.py status
  python scripts/cli.py pause
  python scripts/cli.py resume
  python scripts/cli.py set-floor AMOUNT
  python scripts/cli.py clear-floor
  python scripts/cli.py buy SYMBOL [--notional 50] [--risk-pct 0.01] [--stop-pct 0.05]
  python scripts/cli.py sell SYMBOL
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.config import settings
from trading.data.market_data import load_daily_bars_yfinance
from trading.execution.broker import AlpacaBroker
from trading.execution.positions import record_close, record_open
from trading.execution.state import load_state, set_capital_floor, set_paused
from trading.risk.risk_manager import RiskManager


def cmd_status(_args):
    broker = AlpacaBroker()
    account = broker.client.get_account()
    positions = broker.client.get_all_positions()
    state = load_state()
    equity = float(account.equity)
    capital_floor = state.get("capital_floor")

    print(f"Paused: {state.get('paused', False)}")
    print(f"Equity: {account.equity} {getattr(account, 'currency', 'USD')}")
    print(f"Cash: {account.cash}")
    print(f"Buying power: {account.buying_power}")

    if capital_floor:
        risk = RiskManager(
            equity=equity, risk_per_trade=settings.risk_per_trade, capital_floor=capital_floor, ladder=True
        )
        status = "AT/BELOW FLOOR -- new entries halted" if risk.at_or_below_floor() else "above floor"
        print(
            f"Capital floor: {capital_floor} ({status}); "
            f"effective risk per trade: {risk.effective_risk_per_trade() * 100:.2f}% "
            f"(base {settings.risk_per_trade * 100:.2f}%)"
        )
    else:
        print("Capital floor: not set")

    print(f"Open positions ({len(positions)}):")
    for p in positions:
        print(f"  {p.symbol}: {p.qty} shares @ avg {p.avg_entry_price}, unrealized P&L {p.unrealized_pl}")


def cmd_pause(_args):
    set_paused(True)
    print("Paused. The daily automated run will skip trading until resumed.")


def cmd_resume(_args):
    set_paused(False)
    print("Resumed. The daily automated run will trade again.")


def cmd_set_floor(args):
    set_capital_floor(args.amount)
    print(
        f"Capital floor set to {args.amount}. The daily run will stop opening new positions "
        f"if/while equity is at or below this, and will scale risk per trade by how far above "
        f"it equity has grown (see RiskManager.effective_risk_per_trade)."
    )


def cmd_clear_floor(_args):
    set_capital_floor(None)
    print("Capital floor cleared. Risk per trade reverts to the fixed RISK_PER_TRADE setting.")


def cmd_buy(args):
    symbol = args.symbol.upper()
    broker = AlpacaBroker()
    equity = float(broker.client.get_account().equity)

    import pandas as pd

    end = pd.Timestamp.today().normalize()
    start = (end - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    bars = load_daily_bars_yfinance(symbol, start=start)
    if bars.empty:
        print(f"No price data for {symbol} -- order not placed.")
        return

    price = float(bars["close"].iloc[-1])
    stop_price = price * (1 - args.stop_pct)
    target_price = price * (1 + args.stop_pct * 2)

    if args.notional and args.notional > 0:
        notional = min(args.notional, equity)
    else:
        risk_amount = equity * args.risk_pct
        notional = risk_amount / (args.stop_pct)  # risk_amount == notional * stop_pct

    if notional <= 0:
        print("Computed notional amount is 0 -- order not placed.")
        return

    print(f"Placing BUY {symbol} ~${notional:.2f} @ ~{price:.2f} (stop {stop_price:.2f}, target {target_price:.2f})")
    broker.submit_notional_buy(symbol, notional)
    qty = broker.wait_for_position_qty(symbol)
    if qty <= 0:
        broker.cancel_open_orders(symbol)
        print(
            "Buy did not fill in time (market likely closed) -- cancelled rather than leave an "
            "untracked order that could fill later without stop/target protection. Try again "
            "during market hours."
        )
        return

    broker.submit_stop_sell(symbol, qty, stop_price)
    broker.submit_limit_sell(symbol, qty, target_price)
    record_open(symbol, qty, stop_price, target_price)
    print(f"Filled {qty} shares; stop/target orders placed.")


def cmd_sell(args):
    symbol = args.symbol.upper()
    broker = AlpacaBroker()
    print(f"Closing position: {symbol}")
    broker.close_position(symbol)
    record_close(symbol)
    print("Close order submitted.")


def cmd_cancel(args):
    symbol = args.symbol.upper()
    broker = AlpacaBroker()
    broker.cancel_open_orders(symbol)
    record_close(symbol)
    print(f"Cancelled any open orders for {symbol} (no position to close, just pending orders).")


def main():
    parser = argparse.ArgumentParser(description="Manual control for the trading bot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("pause").set_defaults(func=cmd_pause)
    sub.add_parser("resume").set_defaults(func=cmd_resume)

    floor_parser = sub.add_parser("set-floor")
    floor_parser.add_argument("amount", type=float)
    floor_parser.set_defaults(func=cmd_set_floor)

    sub.add_parser("clear-floor").set_defaults(func=cmd_clear_floor)

    buy_parser = sub.add_parser("buy")
    buy_parser.add_argument("symbol")
    buy_parser.add_argument("--notional", type=float, default=0, help="Dollar amount to buy; overrides risk-based sizing")
    buy_parser.add_argument("--risk-pct", type=float, default=0.01, help="Fraction of equity to risk if --notional is not given")
    buy_parser.add_argument("--stop-pct", type=float, default=0.05, help="Stop-loss distance below entry, as a fraction")
    buy_parser.set_defaults(func=cmd_buy)

    sell_parser = sub.add_parser("sell")
    sell_parser.add_argument("symbol")
    sell_parser.set_defaults(func=cmd_sell)

    cancel_parser = sub.add_parser("cancel")
    cancel_parser.add_argument("symbol")
    cancel_parser.set_defaults(func=cmd_cancel)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

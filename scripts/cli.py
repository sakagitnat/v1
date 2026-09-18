"""Manual control for the trading bot: status, pause/resume, and one-off orders.

Meant to be run by the "Manual Trading Command" GitHub Actions workflow
(workflow_dispatch), which Claude triggers on your behalf when you ask for
something in chat -- it never needs your Alpaca keys directly, since those
live only in the repository's GitHub Actions secrets.

Usage:
  python scripts/cli.py status
  python scripts/cli.py pause
  python scripts/cli.py resume
  python scripts/cli.py buy SYMBOL [--qty N] [--risk-pct 0.01] [--stop-pct 0.05]
  python scripts/cli.py sell SYMBOL
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.data.market_data import load_daily_bars_yfinance
from trading.execution.broker import AlpacaBroker
from trading.execution.state import load_state, set_paused


def cmd_status(_args):
    broker = AlpacaBroker()
    account = broker.client.get_account()
    positions = broker.client.get_all_positions()
    state = load_state()

    print(f"Paused: {state.get('paused', False)}")
    print(f"Equity: {account.equity} {getattr(account, 'currency', 'USD')}")
    print(f"Cash: {account.cash}")
    print(f"Buying power: {account.buying_power}")
    print(f"Open positions ({len(positions)}):")
    for p in positions:
        print(f"  {p.symbol}: {p.qty} shares @ avg {p.avg_entry_price}, unrealized P&L {p.unrealized_pl}")


def cmd_pause(_args):
    set_paused(True)
    print("Paused. The daily automated run will skip trading until resumed.")


def cmd_resume(_args):
    set_paused(False)
    print("Resumed. The daily automated run will trade again.")


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

    if args.qty and args.qty > 0:
        qty = args.qty
    else:
        risk_amount = equity * args.risk_pct
        qty = int(risk_amount // (price - stop_price))

    if qty <= 0:
        print("Computed quantity is 0 -- order not placed.")
        return

    print(f"Placing BUY {symbol} x{qty} @ ~{price:.2f} (stop {stop_price:.2f}, target {target_price:.2f})")
    broker.submit_bracket_buy(symbol, qty, stop_price, target_price)
    print("Order submitted.")


def cmd_sell(args):
    symbol = args.symbol.upper()
    broker = AlpacaBroker()
    print(f"Closing position: {symbol}")
    broker.close_position(symbol)
    print("Close order submitted.")


def main():
    parser = argparse.ArgumentParser(description="Manual control for the trading bot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("pause").set_defaults(func=cmd_pause)
    sub.add_parser("resume").set_defaults(func=cmd_resume)

    buy_parser = sub.add_parser("buy")
    buy_parser.add_argument("symbol")
    buy_parser.add_argument("--qty", type=int, default=0, help="Exact share count; overrides risk-based sizing")
    buy_parser.add_argument("--risk-pct", type=float, default=0.01, help="Fraction of equity to risk if --qty is not given")
    buy_parser.add_argument("--stop-pct", type=float, default=0.05, help="Stop-loss distance below entry, as a fraction")
    buy_parser.set_defaults(func=cmd_buy)

    sell_parser = sub.add_parser("sell")
    sell_parser.add_argument("symbol")
    sell_parser.set_defaults(func=cmd_sell)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

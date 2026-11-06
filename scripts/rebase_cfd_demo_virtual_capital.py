"""Safely rebase the Deriv DEMO account onto the configured virtual capital.

This is a one-time migration tool for legacy state where broker_baseline was
captured before the current $100 virtual-capital model. It refuses to run if
there is any evidence of bot trading history or any open/pending position, so
it cannot erase genuine P&L.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker
from trading.cfd.state import (
    get_pending_entries,
    list_open_trades,
    rebase_demo_virtual_capital,
)
from trading.cfd.trade_log import load_trades
from trading.config import settings


async def main() -> None:
    if settings.cfd_allow_live_trading:
        raise SystemExit("Refusing rebase while CFD_ALLOW_LIVE_TRADING=true")

    trades = load_trades()
    if trades:
        raise SystemExit(f"Refusing rebase: {len(trades)} recorded bot trade(s) exist.")

    tracked = list_open_trades()
    if tracked:
        raise SystemExit(f"Refusing rebase: {len(tracked)} locally tracked open contract(s) exist.")

    pending = get_pending_entries()
    if pending:
        raise SystemExit(f"Refusing rebase: pending entries exist for {list(pending)}")

    broker = DerivBroker()
    try:
        account = await broker.connect()
        if account.get("account_type") != "demo":
            raise SystemExit(f"Refusing rebase: connected account is {account.get('account_type')!r}, not demo.")
        broker_positions = await broker.open_positions_list()
        if broker_positions:
            raise SystemExit(f"Refusing rebase: {len(broker_positions)} broker-side open contract(s) exist.")
        balance = await broker.account_equity()
        rebase_demo_virtual_capital(balance, settings.cfd_virtual_starting_capital)
        print(
            f"REBASING COMPLETE: broker_baseline={balance:.2f}, "
            f"virtual_equity={settings.cfd_virtual_starting_capital:.2f}, "
            f"high_water_mark={settings.cfd_virtual_starting_capital:.2f}"
        )
    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(main())

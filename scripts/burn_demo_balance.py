"""One-off utility: brings the DEMO account's balance down from Deriv's
fixed $10,000 default to roughly TARGET_BALANCE, so Monday's real
order-placement validation (and the live bot's first real runs after
that) size positions against a realistic ~$100 starting balance instead
of $10,000 -- risk_per_trade-based position sizing scales with equity,
so leaving $10,000 in place would make every stake ~100x larger than
what the account will actually have once real money is involved.

Deriv's demo accounts cannot be set to a custom balance directly (only
reset back to the fixed $10,000 default -- confirmed via Deriv's own
docs/community, no API for an arbitrary amount) -- trading it down is
the documented workaround, so that's what this does, deliberately and
transparently.

How it stays roughly on target rather than swinging unpredictably:
each round opens a position with stop_loss_amount == stake (so the
worst case loses exactly the stake, per Deriv's capped-loss guarantee)
and take_profit_amount == stake * TAKE_PROFIT_RATIO (several times
farther away in price-move terms, since P&L moves roughly linearly
with price for a Multiplier contract -- see backtest.py's _pnl). That
makes the stop-loss threshold far more likely to be crossed first on a
volatile, directionless instrument (Volatility 100 Index -- a
synthetic index with no real-world trend to bias it), so most rounds
end in a small loss, not a rare large win. Each round's stake is a
fraction of the remaining distance to target, so even a worst-case
string of max-loss rounds converges toward the target rather than
overshooting far past it, and the loop stops as soon as equity is
within TOLERANCE of TARGET_BALANCE regardless.

Only ever runs against a DEMO account -- broker.connect()'s existing
safety gate refuses a real account unless CFD_ALLOW_LIVE_TRADING is
set, same as every other command in this project.

Usage: python scripts/burn_demo_balance.py [--target 100] [--tolerance 30] [--instrument R_100] [--multiplier 400]
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker

LOSS_FRACTION_OF_REMAINING = 0.20  # each round's stake is this fraction of (equity - target)
TAKE_PROFIT_RATIO = 8.0  # take_profit_amount = stake * this -- far enough that stop_loss wins most of the time
MIN_STAKE = 1.0
MAX_STAKE = 1000.0  # confirmed live: "Maximum stake allowed is 1000.00" -- not documented ahead of time, discovered via the real error
MAX_ROUNDS = 60
POLL_INTERVAL_SECONDS = 5
MAX_WAIT_PER_ROUND_SECONDS = 90  # force-close if Deriv hasn't auto-closed it by itself yet


async def main(target: float, tolerance: float, instrument: str, multiplier: int):
    broker = DerivBroker()
    try:
        account = await broker.connect()
        print(f"Connected: account_id={account.get('account_id')} account_type={account.get('account_type')}")
        if account.get("account_type") != "demo":
            raise RuntimeError("Refusing to run: this is not a demo account (should be unreachable -- connect() should have refused already).")

        equity = await broker.account_equity()
        print(f"Starting equity: {equity:.2f} -- target {target:.2f} (+/- {tolerance:.2f})")

        rounds = 0
        while equity - target > tolerance and rounds < MAX_ROUNDS:
            rounds += 1
            remaining = equity - target
            stake = max(MIN_STAKE, round(min(remaining * LOSS_FRACTION_OF_REMAINING, remaining, MAX_STAKE), 2))
            stop_loss_amount = stake
            take_profit_amount = round(stake * TAKE_PROFIT_RATIO, 2)
            side = "long" if rounds % 2 == 0 else "short"  # alternate direction, no reason to bias one way

            print(
                f"\nRound {rounds}: equity={equity:.2f}, remaining={remaining:.2f}, "
                f"stake={stake:.2f} (stop=-{stop_loss_amount:.2f}, target=+{take_profit_amount:.2f}), side={side}"
            )
            result = await broker.submit_multiplier_order(instrument, side, stake, multiplier, stop_loss_amount, take_profit_amount)
            contract_id = result.get("buy", {}).get("contract_id")
            if contract_id is None:
                print(f"  No contract_id in response -- skipping this round: {result!r}")
                continue

            waited = 0
            while waited < MAX_WAIT_PER_ROUND_SECONDS:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                waited += POLL_INTERVAL_SECONDS
                positions = await broker.open_positions()
                if instrument not in positions or positions[instrument].get("contract_id") != contract_id:
                    print(f"  Closed on its own (stop or target hit) after {waited}s")
                    break
            else:
                print(f"  Still open after {MAX_WAIT_PER_ROUND_SECONDS}s -- closing manually")
                try:
                    await broker.close_position(contract_id)
                except RuntimeError as e:
                    print(f"  close_position failed (may have just closed itself): {e}")

            equity = await broker.account_equity()
            print(f"  Equity now: {equity:.2f}")

        print(f"\nDone after {rounds} round(s). Final equity: {equity:.2f} (target was {target:.2f} +/- {tolerance:.2f})")
        if equity - target > tolerance:
            print(f"Did not fully reach target within {MAX_ROUNDS} rounds -- re-run to continue, or accept the current balance.")
    finally:
        await broker.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=float, default=100.0)
    parser.add_argument("--tolerance", type=float, default=30.0)
    parser.add_argument("--instrument", default="R_100", help="Volatility 100 Index by default: always open, no real-world trend to bias direction")
    parser.add_argument("--multiplier", type=int, default=400, help="R_100's highest accepted multiplier (confirmed earlier: 40/100/200/300/400) -- smaller price moves needed to hit either threshold")
    args = parser.parse_args()
    asyncio.run(main(args.target, args.tolerance, args.instrument, args.multiplier))

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
each position opens with stop_loss_amount == its stake (so the worst
case loses exactly the stake, per Deriv's capped-loss guarantee) and
take_profit_amount == stake * TAKE_PROFIT_RATIO (several times farther
away in price-move terms, since P&L moves roughly linearly with price
for a Multiplier contract -- see backtest.py's _pnl). That makes the
stop-loss threshold far more likely to be crossed first on a volatile,
directionless instrument, so most positions end in a small loss, not a
rare large win. Each round's total stake is a fraction of the
remaining distance to target, so even a worst-case string of max-loss
rounds converges toward the target rather than overshooting far past
it, and the loop stops as soon as equity is within TOLERANCE of
TARGET_BALANCE regardless.

Runs CONCURRENT_INSTRUMENTS positions at once per round (one each on
Volatility 10/25/50/75/100 -- all always-open synthetic indices, so a
single Deriv account can hold several simultaneously without the "one
position per symbol" ambiguity a real trading strategy would have) so
each round's wait is one shared poll loop instead of N sequential
waits -- roughly N times faster wall-clock for the same amount burned.

Only ever runs against a DEMO account -- broker.connect()'s existing
safety gate refuses a real account unless CFD_ALLOW_LIVE_TRADING is
set, same as every other command in this project.

Usage: python scripts/burn_demo_balance.py [--target 100] [--tolerance 30] [--multiplier 400]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker

CONCURRENT_INSTRUMENTS = ["R_100", "R_75", "R_50", "R_25", "R_10"]
LOSS_FRACTION_OF_REMAINING = 0.20  # each round's TOTAL stake (across all concurrent positions) is this fraction of (equity - target)
TAKE_PROFIT_RATIO = 8.0  # take_profit_amount = stake * this -- far enough that stop_loss wins most of the time
MIN_STAKE = 1.0
MAX_STAKE = 1000.0  # confirmed live: "Maximum stake allowed is 1000.00" -- not documented ahead of time, discovered via the real error
MAX_ROUNDS = 20  # fewer rounds needed now that each round burns ~5x more per wait cycle
POLL_INTERVAL_SECONDS = 5
MAX_WAIT_PER_ROUND_SECONDS = 90  # force-close whatever's still open after this long


async def main(target: float, tolerance: float, multiplier: int):
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
            total_stake = max(MIN_STAKE, min(remaining * LOSS_FRACTION_OF_REMAINING, remaining, MAX_STAKE * len(CONCURRENT_INSTRUMENTS)))
            per_stake = round(max(MIN_STAKE, min(total_stake / len(CONCURRENT_INSTRUMENTS), MAX_STAKE)), 2)
            stop_loss_amount = per_stake
            take_profit_amount = round(per_stake * TAKE_PROFIT_RATIO, 2)

            print(f"\nRound {rounds}: equity={equity:.2f}, remaining={remaining:.2f}, per_stake={per_stake:.2f} across {len(CONCURRENT_INSTRUMENTS)} instruments")

            opened: dict[str, int] = {}
            for i, instrument in enumerate(CONCURRENT_INSTRUMENTS):
                side = "long" if (rounds + i) % 2 == 0 else "short"  # alternate, no reason to bias one way
                try:
                    result = await broker.submit_multiplier_order(instrument, side, per_stake, multiplier, stop_loss_amount, take_profit_amount)
                    contract_id = result.get("buy", {}).get("contract_id")
                    if contract_id is None:
                        print(f"  {instrument}: no contract_id in response -- skipping: {result!r}")
                        continue
                    opened[instrument] = contract_id
                    print(f"  Opened {side} {instrument} stake={per_stake:.2f} contract_id={contract_id}")
                except RuntimeError as e:
                    print(f"  {instrument}: failed to open ({e}) -- skipping this slot")

            if not opened:
                print("  No positions opened this round -- retrying next round")
                equity = await broker.account_equity()
                continue

            waited = 0
            while waited < MAX_WAIT_PER_ROUND_SECONDS and opened:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                waited += POLL_INTERVAL_SECONDS
                positions = await broker.open_positions()
                still_open = {}
                for instrument, cid in opened.items():
                    pos = positions.get(instrument)
                    if pos is not None and pos.get("contract_id") == cid:
                        still_open[instrument] = cid
                    else:
                        print(f"  {instrument} (contract {cid}) closed on its own after {waited}s")
                opened = still_open

            for instrument, cid in opened.items():
                print(f"  {instrument} (contract {cid}) still open after {MAX_WAIT_PER_ROUND_SECONDS}s -- closing manually")
                try:
                    await broker.close_position(cid)
                except RuntimeError as e:
                    print(f"    close_position failed (may have just closed itself): {e}")

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
    parser.add_argument("--multiplier", type=int, default=400, help="R_100's highest accepted multiplier (confirmed earlier: 40/100/200/300/400) -- applied to all CONCURRENT_INSTRUMENTS; if one rejects it, that slot is skipped for the round (see the RuntimeError handling) rather than crashing the whole run")
    args = parser.parse_args()
    asyncio.run(main(args.target, args.tolerance, args.multiplier))

"""DEPRECATED -- do not run this again. Kept only as documented history.

The project's master vision (docs/VISION.md) now explicitly forbids
deliberately trading an account's balance down or up to hit a target
number -- exactly what this script does. It predates that rule and was a
deliberate, transparent workaround at the time (see docs/
ARCHITECTURE_AUDIT.md for the full writeup), but the problem it solved
(sizing positions realistically against ~$100 instead of Deriv's fixed
~$10,000 demo default) is now solved the correct way instead:
trading.cfd.capital rebases every risk/performance calculation onto a
*virtual* equity derived from the real balance, without ever touching the
real balance itself. Use that -- see scheduler.py and cfd_cli.py status.

Left in the repo, unchanged below, only because it's real documented
history of a genuine Deriv API constraint (no API to reset a demo account
to an arbitrary balance) that a future contributor might otherwise
rediscover the hard way. Running it now requires an explicit
--i-understand-this-is-deprecated flag specifically so nothing (human or
automated) can invoke it by accident; it is also no longer offered as a
choice in the "CFD Manual Command" GitHub Actions workflow.

---

Original docstring, for the history described above:

One-off utility: brings the DEMO account's balance down from Deriv's
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

Second attempt -- the first version (multiple different Volatility
indices, stop_loss_amount == full stake, 90s timeout) mostly FAILED to
converge: nearly every position timed out at 90s without ever hitting
either threshold, so the force-close realized whatever P&L happened to
exist at an arbitrary moment -- not biased toward loss at all, hence
equity oscillating instead of trending down. Root cause, worked out
from that run's numbers: R_100's typical move over 90s is roughly
0.17%, but stop_loss_amount == stake requires a 1/multiplier = 0.25%
move (multiplier=400) to trigger -- bigger than what usually happens
in that window, so timeouts (not stop-losses) dominated.

Fix: stop_loss_amount is now a SMALL fraction of the stake (so the
required price move is much smaller and triggers quickly and
reliably), take_profit_amount stays TAKE_PROFIT_RATIO times farther
(preserving the loss-bias), and the timeout is generous (rarely
needed, just a safety net for the unlucky tail). Also switched to
running several SIMULTANEOUS positions on R_100 alone (the fastest
mover, and the one instrument with a confirmed-accepted multiplier of
400) via open_contract_ids() rather than mixing in slower Volatility
indices whose accepted multipliers/dynamics weren't confirmed and, per
the first run's log, kept timing out too.

Only ever runs against a DEMO account -- broker.connect()'s existing
safety gate refuses a real account unless CFD_ALLOW_LIVE_TRADING is
set, same as every other command in this project.

Third revision: the second attempt's logic actually worked (equity
dropped steadily, e.g. $5700 -> $2300 over ~22 rounds) but the run
died partway through on `websockets.exceptions.ConnectionClosedError:
no close frame received or sent` after about 30 minutes connected --
Deriv's WebSocket apparently doesn't stay open indefinitely. Added
reconnection: any round that raises is treated as a dropped
connection, the broker reconnects, any position left dangling from the
interrupted round is swept up and closed, and the loop continues from
the current (freshly re-fetched) equity rather than dying.

Usage: python scripts/burn_demo_balance.py [--target 100] [--tolerance 30] [--multiplier 400]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker

INSTRUMENT = "R_100"  # confirmed: fastest-moving of the Volatility indices tried, accepts multiplier 400
CONCURRENT_POSITIONS = 5
LOSS_FRACTION_OF_REMAINING = 0.25  # each round's TOTAL stake (across all concurrent positions) is this fraction of (equity - target)
STOP_LOSS_FRACTION_OF_STAKE = 0.4  # stop_loss_amount = per_stake * this -- required price move = this/multiplier (0.4/400 = 0.1%, well within R_100's ~0.17%/90s typical move)
TAKE_PROFIT_RATIO = 8.0  # take_profit_amount = stop_loss_amount * this -- far enough that stop_loss wins most of the time
MIN_STAKE = 1.0
MAX_STAKE = 1000.0  # confirmed live: "Maximum stake allowed is 1000.00"
MAX_ROUNDS = 30
POLL_INTERVAL_SECONDS = 5
MAX_WAIT_PER_ROUND_SECONDS = 240  # safety net -- most positions should close well before this now
MAX_RECONNECTS = 10


async def _run_round(broker: DerivBroker, rounds: int, equity: float, target: float, multiplier: int) -> float:
    """Runs one round to completion and returns the equity afterward.
    Raises on any connection/API failure -- the caller decides whether
    to reconnect and retry."""
    remaining = equity - target
    total_stake = max(MIN_STAKE, min(remaining * LOSS_FRACTION_OF_REMAINING, remaining, MAX_STAKE * CONCURRENT_POSITIONS))
    per_stake = round(max(MIN_STAKE, min(total_stake / CONCURRENT_POSITIONS, MAX_STAKE)), 2)
    stop_loss_amount = round(per_stake * STOP_LOSS_FRACTION_OF_STAKE, 2)
    take_profit_amount = round(stop_loss_amount * TAKE_PROFIT_RATIO, 2)

    print(
        f"\nRound {rounds}: equity={equity:.2f}, remaining={remaining:.2f}, per_stake={per_stake:.2f} "
        f"(stop=-{stop_loss_amount:.2f}, target=+{take_profit_amount:.2f}) x{CONCURRENT_POSITIONS} on {INSTRUMENT}"
    )

    opened: set[int] = set()
    for i in range(CONCURRENT_POSITIONS):
        side = "long" if (rounds + i) % 2 == 0 else "short"  # alternate, no reason to bias one way
        try:
            result = await broker.submit_multiplier_order(INSTRUMENT, side, per_stake, multiplier, stop_loss_amount, take_profit_amount)
            contract_id = result.get("buy", {}).get("contract_id")
            if contract_id is None:
                print(f"  slot {i}: no contract_id in response -- skipping: {result!r}")
                continue
            opened.add(contract_id)
            print(f"  Opened {side} contract_id={contract_id}")
        except RuntimeError as e:
            print(f"  slot {i}: failed to open ({e}) -- skipping this slot")

    if not opened:
        print("  No positions opened this round -- retrying next round")
        return await broker.account_equity()

    waited = 0
    while waited < MAX_WAIT_PER_ROUND_SECONDS and opened:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS
        still_open_ids = await broker.open_contract_ids()
        closed_now = opened - still_open_ids
        for cid in closed_now:
            print(f"  contract {cid} closed on its own after {waited}s")
        opened &= still_open_ids

    for cid in opened:
        print(f"  contract {cid} still open after {MAX_WAIT_PER_ROUND_SECONDS}s -- closing manually")
        try:
            await broker.close_position(cid)
        except RuntimeError as e:
            print(f"    close_position failed (may have just closed itself): {e}")

    equity = await broker.account_equity()
    print(f"  Equity now: {equity:.2f}")
    return equity


async def _reconnect(broker: DerivBroker) -> DerivBroker:
    """Closes whatever's left of the old (dead) connection, opens a
    fresh one, and sweeps up any position left dangling from a round
    that died mid-flight -- an open contract from before the drop is
    still open on Deriv's side regardless of what killed our WebSocket."""
    try:
        await broker.close()
    except Exception:
        pass
    new_broker = DerivBroker()
    await new_broker.connect()
    leftover = await new_broker.open_contract_ids()
    for cid in leftover:
        print(f"  Reconnect cleanup: closing dangling contract {cid} from the interrupted round")
        try:
            await new_broker.close_position(cid)
        except RuntimeError as e:
            print(f"    close_position failed (may have just closed itself): {e}")
    return new_broker


async def main(target: float, tolerance: float, multiplier: int):
    broker = DerivBroker()
    account = await broker.connect()
    print(f"Connected: account_id={account.get('account_id')} account_type={account.get('account_type')}")
    if account.get("account_type") != "demo":
        await broker.close()
        raise RuntimeError("Refusing to run: this is not a demo account (should be unreachable -- connect() should have refused already).")

    equity = await broker.account_equity()
    print(f"Starting equity: {equity:.2f} -- target {target:.2f} (+/- {tolerance:.2f})")

    rounds = 0
    reconnects = 0
    try:
        while equity - target > tolerance and rounds < MAX_ROUNDS:
            rounds += 1
            try:
                equity = await _run_round(broker, rounds, equity, target, multiplier)
            except Exception as e:
                reconnects += 1
                if reconnects > MAX_RECONNECTS:
                    print(f"\nToo many reconnects ({reconnects}) -- giving up. Last error: {e!r}")
                    break
                print(f"\nRound {rounds} failed ({e!r}) -- reconnecting (attempt {reconnects}/{MAX_RECONNECTS})...")
                rounds -= 1  # this round didn't complete -- retry it, don't count it as done
                await asyncio.sleep(5)
                broker = await _reconnect(broker)
                equity = await broker.account_equity()
                print(f"Reconnected. Equity: {equity:.2f}")

        print(f"\nDone after {rounds} round(s) ({reconnects} reconnect(s)). Final equity: {equity:.2f} (target was {target:.2f} +/- {tolerance:.2f})")
        if equity - target > tolerance:
            print(f"Did not fully reach target within {MAX_ROUNDS} rounds -- re-run to continue, or accept the current balance.")
    finally:
        await broker.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=float, default=100.0)
    parser.add_argument("--tolerance", type=float, default=30.0)
    parser.add_argument("--multiplier", type=int, default=400, help="R_100's highest accepted multiplier (confirmed earlier: 40/100/200/300/400)")
    parser.add_argument(
        "--i-understand-this-is-deprecated",
        action="store_true",
        help="Required. This script is deprecated -- see its module docstring. "
        "trading.cfd.capital's virtual equity model is the correct replacement.",
    )
    args = parser.parse_args()
    if not args.i_understand_this_is_deprecated:
        print(
            "Refusing to run: this script is DEPRECATED (see its module docstring and "
            "docs/VISION.md's prohibition on deliberately trading a balance down or up "
            "to hit a target). Use trading.cfd.capital's virtual equity model instead. "
            "Pass --i-understand-this-is-deprecated to run it anyway.",
            file=sys.stderr,
        )
        sys.exit(1)
    asyncio.run(main(args.target, args.tolerance, args.multiplier))

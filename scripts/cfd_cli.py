"""Manual control for the CFD/forex (Deriv) bot: status, pause/resume,
excluding an instrument. Mirrors scripts/cli.py's pattern for the stock
system but is a completely separate account/state file.

Meant to be run by a "CFD Manual Command" GitHub Actions workflow
(workflow_dispatch), triggered from chat -- never needs the Deriv token
directly, since it lives only in the repository's GitHub Actions secrets.

Instrument names are Deriv's own, mixed-case and case-sensitive
(e.g. frxXAUUSD for gold, not XAU_USD or FRXXAUUSD).

Usage:
  python scripts/cfd_cli.py status
  python scripts/cfd_cli.py performance
  python scripts/cfd_cli.py paper-performance
  python scripts/cfd_cli.py failures
  python scripts/cfd_cli.py manager-report
  python scripts/cfd_cli.py list-strategies
  python scripts/cfd_cli.py promote-strategy NAME VERSION STATE --reason "..."
  python scripts/cfd_cli.py pause [--reason "..."]
  python scripts/cfd_cli.py resume
  python scripts/cfd_cli.py set-mode {defensive,normal,aggressive,recovery} [--reason "..."]
  python scripts/cfd_cli.py set-floor AMOUNT
  python scripts/cfd_cli.py clear-floor
  python scripts/cfd_cli.py exclude-instrument frxXAUUSD [--reason "..."]
  python scripts/cfd_cli.py include-instrument frxXAUUSD
  python scripts/cfd_cli.py test-order [--instrument frxXAUUSD] [--side long]
  python scripts/cfd_cli.py close-position CONTRACT_ID
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.broker import DerivBroker
from trading.cfd.capital import equity_for_account
from trading.cfd.failure_analysis import detect_degradation, summarize_losses
from trading.cfd.manager_report import build_report
from trading.cfd.operating_mode import VALID_MODES
from trading.cfd.paper_trading import PAPER_LOG_PATH
from trading.cfd.performance import compute_performance
from trading.cfd.state import (
    exclude_instrument,
    include_instrument,
    list_open_trades,
    load_state,
    set_capital_floor,
    set_operating_mode,
    set_paused,
)
from trading.cfd.strategy_registry import LifecycleState, list_all, set_state
from trading.cfd.trade_log import load_trades
from trading.config import settings


async def cmd_status(_args):
    broker = DerivBroker()
    try:
        account = await broker.connect()
        state = load_state()
        broker_balance = await broker.account_equity()
        broker_baseline = state.get("broker_baseline")
        equity = equity_for_account(
            broker_balance, account.get("account_type"), broker_baseline, settings.cfd_virtual_starting_capital
        )
        # open_positions_list(), not open_positions() -- a partial-close
        # split (trading.cfd.exit_manager) can leave two simultaneous
        # legs open on the same instrument, which open_positions()'s
        # symbol-collapsed dict would silently hide one of.
        positions = await broker.open_positions_list()

        pause_note = f" ({state.get('pause_reason')})" if state.get("paused") and state.get("pause_reason") else ""
        print(f"Paused: {state.get('paused', False)}{pause_note}")
        mode = state.get("operating_mode", "normal")
        mode_note = f" ({state.get('operating_mode_reason')})" if state.get("operating_mode_reason") else ""
        print(f"Operating mode: {mode}{mode_note}")
        if account.get("account_type") == "demo" and broker_baseline is not None:
            print(f"Broker balance (raw demo, not the real number): {broker_balance:.2f}")
            print(f"Broker baseline (recorded at first run): {broker_baseline:.2f}")
            print(f"Virtual equity (use this one): {equity:.2f}")
        else:
            print(f"Equity: {equity:.2f}")
        floor = state.get("capital_floor")
        print(f"Capital floor (virtual equity terms): {floor if floor is not None else 'none set -- see set-floor'}")
        start = settings.cfd_virtual_starting_capital
        growth = equity - start
        growth_pct = (growth / start * 100) if start > 0 else 0.0
        print(f"Growth since virtual start: {growth:+.2f} ({growth_pct:+.1f}%) -- virtual starting capital {start:.2f}")

        excluded = state.get("excluded_instruments") or {}
        if excluded:
            print(f"Excluded instruments: {excluded}")

        tracked_open = list_open_trades()
        print(f"Open positions ({len(positions)}):")
        for pos in positions:
            meta = tracked_open.get(str(pos["contract_id"])) or {}
            leg_note = f", leg={meta['leg']}" if meta.get("leg") else ""
            print(f"  {pos['instrument']}: {pos['side']} (contract {pos['contract_id']}{leg_note})")
    finally:
        await broker.close()


def cmd_performance(_args):
    """Prints the Performance Engine's metrics computed from the Trade
    Database (state/cfd_trades.jsonl) -- see trading.cfd.performance.
    Synchronous and offline: reads the local trade log only, no Deriv
    connection needed."""
    trades = load_trades()
    if not trades:
        print("No trades recorded yet (state/cfd_trades.jsonl is empty or missing).")
        return
    metrics = compute_performance(trades, starting_equity=settings.cfd_virtual_starting_capital)
    print(f"Trades: {metrics['trade_count']} ({metrics['priced_trade_count']} priced, {metrics['unattributed_trade_count']} unattributed)")
    print(f"Net return: {metrics['net_return']:+.2f} (starting capital {settings.cfd_virtual_starting_capital:.2f})")
    print(f"Expectancy: {metrics['expectancy']:+.2f} per trade")
    print(f"Win rate: {metrics['win_rate_pct']:.1f}%  Profit factor: {metrics['profit_factor']}")
    print(f"Avg win: {metrics['avg_win']:+.2f}  Avg loss: {metrics['avg_loss']:+.2f}  Avg R: {metrics['avg_r_multiple']}")
    print(f"Sharpe: {metrics['sharpe']}  Sortino: {metrics['sortino']}  Calmar: {metrics['calmar']}")
    print(f"Max drawdown: {metrics['max_drawdown_pct']:.2f}%  Longest losing streak: {metrics['longest_losing_streak']}")
    print(f"Exposure: {metrics['exposure_pct']}%")
    for label, key in [("strategy", "by_strategy"), ("regime", "by_regime"), ("session", "by_session"), ("side", "by_side")]:
        print(f"By {label}:")
        for name, stats in metrics[key].items():
            print(f"  {name}: {stats}")


def cmd_paper_performance(_args):
    """Same as `performance`, but for the separate Paper Trading log
    (state/cfd_paper_trades.jsonl) -- see trading.cfd.paper_trading.
    Every PAPER-state strategy's simulated results, never mixed with the
    real Trade Database."""
    trades = load_trades(PAPER_LOG_PATH)
    if not trades:
        print("No paper trades recorded yet (no strategy is in PAPER state, or none has traded yet).")
        return
    metrics = compute_performance(trades, starting_equity=settings.cfd_virtual_starting_capital)
    print(f"Paper trades: {metrics['trade_count']} ({metrics['priced_trade_count']} priced)")
    print(f"Net return: {metrics['net_return']:+.2f}  Expectancy: {metrics['expectancy']:+.2f} per trade")
    print(f"Win rate: {metrics['win_rate_pct']:.1f}%  Profit factor: {metrics['profit_factor']}")
    print(f"Max drawdown: {metrics['max_drawdown_pct']:.2f}%")
    print("By strategy:")
    for name, stats in metrics["by_strategy"].items():
        print(f"  {name}: {stats}")


def cmd_manager_report(_args):
    """Prints the AI Trading Manager's consolidated report
    (trading.cfd.manager_report): overall performance, loss breakdown,
    every registered strategy grouped by lifecycle state, the current
    Portfolio Allocation weight per ACTIVE strategy and Portfolio Risk
    Governor ceiling utilization (trading.cfd.portfolio_allocator /
    portfolio_risk -- the live scheduler already applies both every run,
    this just makes them visible), and concrete recommended cfd_cli.py
    commands -- never applied automatically. See that module's docstring
    for why lifecycle changes always stay a human's deliberate, audited
    decision."""
    trades = load_trades()
    paper_trades = load_trades(PAPER_LOG_PATH)
    report = build_report(trades, paper_trades)

    perf = report["overall_performance"]
    print(f"Overall: {perf['trade_count']} trades, net return {perf['net_return']:+.2f}, expectancy {perf['expectancy']:+.2f}")

    print("\nRegistry summary:")
    for state_name, tags in report["registry_summary"].items():
        if tags:
            print(f"  {state_name}: {', '.join(tags)}")

    print("\nPortfolio allocation (current risk weight per ACTIVE strategy):")
    if not report["allocation_summary"]:
        print("  (no ACTIVE strategies)")
    for tag, weight in report["allocation_summary"].items():
        print(f"  {tag}: {weight:.2%}")

    risk_summary = report["portfolio_risk_summary"]
    ceilings = risk_summary["ceilings"]
    print(f"\nPortfolio Risk Governor (equity basis: ${risk_summary['equity_basis']:.2f}, {risk_summary['equity_basis_note']}):")
    print(f"  Open positions: {risk_summary['open_position_count']}")
    print(f"  Total portfolio risk: ${risk_summary['total_portfolio_risk']:.2f} (ceiling {ceilings['max_portfolio_risk_pct']:.2%} of equity)")
    print(f"  Total notional exposure: ${risk_summary['total_notional_exposure']:.2f} (ceiling {ceilings['max_exposure_multiple']:.2f}x equity)")
    if risk_summary["thesis_risk"]:
        print("  By thesis:")
        for key, amount in risk_summary["thesis_risk"].items():
            print(f"    {key}: ${amount:.2f} (ceiling {ceilings['max_thesis_risk_pct']:.2%} of equity)")
    if risk_summary["correlated_risk"]:
        print("  By correlated factor group:")
        for key, amount in risk_summary["correlated_risk"].items():
            print(f"    {key}: ${amount:.2f} (ceiling {ceilings['max_correlated_risk_pct']:.2%} of equity)")

    print("\nLoss breakdown:")
    if not report["loss_breakdown"]:
        print("  (no losing trades yet)")
    for category, stats in report["loss_breakdown"].items():
        print(f"  {category}: {stats['count']} trade(s), total {stats['total_pnl']:+.2f}")

    print("\nRecommendations:")
    if not report["recommendations"]:
        print("  (none -- nothing needs attention right now)")
    for rec in report["recommendations"]:
        print(f"  [{rec['type']}] {rec['strategy']}: {rec['reason']}")
        print(f"    -> {rec['command']}")


def cmd_failures(_args):
    """Prints the Failure Analysis breakdown (trading.cfd.failure_analysis)
    computed from the Trade Database: why losing trades lost, and whether
    any registered strategy's recent performance looks degraded versus
    its own history. Offline: no Deriv connection needed. Never changes
    anything -- a degradation flag here is a prompt to look, not an
    automatic pause; use `promote-strategy ... PAUSED` yourself if it
    warrants it."""
    trades = load_trades()
    if not trades:
        print("No trades recorded yet.")
        return

    summary = summarize_losses(trades)
    if not summary:
        print("No losing trades yet.")
    else:
        print("Loss breakdown:")
        for category, stats in sorted(summary.items(), key=lambda kv: kv[1]["total_pnl"]):
            print(f"  {category}: {stats['count']} trade(s), total {stats['total_pnl']:+.2f}, contracts={stats['contract_ids']}")

    print("\nStrategy degradation check:")
    strategy_tags = sorted({t["strategy"] for t in trades if t.get("strategy")})
    if not strategy_tags:
        print("  (no tagged trades yet)")
    for tag in strategy_tags:
        result = detect_degradation(trades, tag)
        if result is None:
            print(f"  {tag}: not enough history yet")
        elif result["degraded"]:
            print(f"  {tag}: DEGRADED -- {result['reason']}")
        else:
            print(f"  {tag}: OK (recent expectancy {result['recent_expectancy']:+.2f} vs prior {result['prior_expectancy']:+.2f})")


def cmd_list_strategies(_args):
    """Prints every strategy registered in the Strategy Registry
    (state/cfd_strategy_registry.json) with its current lifecycle state --
    see trading.cfd.strategy_registry and docs/VISION.md's "Strategy
    lifecycle" section. Offline: no Deriv connection needed."""
    entries = list_all()
    if not entries:
        print("No strategies registered yet. Run scripts/seed_strategy_registry.py first.")
        return
    for e in sorted(entries, key=lambda e: (e.name, e.version)):
        print(f"{e.name}@{e.version}: {e.state}  (updated {e.updated_at})")
        print(f"  params: {e.params}")
        last = e.history[-1] if e.history else None
        if last:
            print(f"  last change: {last['from']} -> {last['to']} ({last['reason']})")


def cmd_promote_strategy(args):
    """Transitions a registered strategy to a new lifecycle state. Enforces
    the pipeline order (RESEARCH -> CANDIDATE -> VALIDATED -> PAPER ->
    ACTIVE, one stage at a time; PAUSED only from/to ACTIVE; RETIRED from
    anywhere but nowhere back out of it) -- see trading.cfd.
    strategy_registry.set_state()'s docstring. A reason is required."""
    try:
        target_state = LifecycleState(args.state)
    except ValueError:
        valid = ", ".join(s.value for s in LifecycleState)
        print(f"Invalid state {args.state!r} -- must be one of: {valid}", file=sys.stderr)
        sys.exit(1)
    try:
        entry = set_state(args.name, args.version, target_state, args.reason)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"{entry.name}@{entry.version} is now {entry.state}.")


async def cmd_list_symbols(args):
    """Diagnostic: prints Deriv's own tradable symbol list (optionally
    filtered by a case-insensitive substring, e.g. --filter crypto or
    --filter BTC) so real instrument names can be confirmed rather than
    guessed -- see broker.py's list_active_symbols()."""
    broker = DerivBroker()
    try:
        await broker.connect()
        symbols = await broker.list_active_symbols()
        needle = (args.filter or "").lower()
        matches = [
            s for s in symbols
            if needle in s.get("underlying_symbol", "").lower()
            or needle in s.get("underlying_symbol_name", "").lower()
            or needle in s.get("market", "").lower()
            or needle in s.get("submarket", "").lower()
        ]
        print(f"{len(matches)}/{len(symbols)} symbols match filter {args.filter!r}:")
        for s in matches:
            print(
                f"  {s.get('underlying_symbol')}: {s.get('underlying_symbol_name')} "
                f"(market={s.get('market')}, submarket={s.get('submarket')}, "
                f"exchange_is_open={s.get('exchange_is_open')}, is_trading_suspended={s.get('is_trading_suspended')})"
            )
    finally:
        await broker.close()


async def cmd_test_order(args):
    """Diagnostic only -- opens a minimal-size real order via the live
    Deriv API (same submit_multiplier_order/close_position path the
    automated strategy uses) and closes it right away, to validate that
    path end-to-end against a live response. Refuses to run against a
    real (non-virtual) account via the same connect()-time safety gate as
    everything else -- see broker.py.

    Not part of the automated strategy loop (scheduler.py) and never
    invoked by it -- this is a manual, one-shot check."""
    broker = DerivBroker()
    try:
        account = await broker.connect()
        print(f"Connected: account_id={account.get('account_id')} account_type={account.get('account_type')}")

        stake, stop_loss_amount, take_profit_amount = 1.0, 0.50, 1.00
        multiplier = args.multiplier
        print(
            f"Submitting {args.side} {args.instrument} stake=${stake:.2f} multiplier={multiplier} "
            f"(stop-loss $-{stop_loss_amount:.2f}, take-profit $+{take_profit_amount:.2f})..."
        )
        result = await broker.submit_multiplier_order(
            args.instrument, args.side, stake, multiplier, stop_loss_amount, take_profit_amount
        )
        contract_id = result.get("buy", {}).get("contract_id")
        if contract_id is None:
            print(f"No contract_id in response -- raw result: {result!r}")
            return
        print(f"Opened contract_id={contract_id}. Raw buy response: {result!r}")

        positions = await broker.open_positions()
        print(f"open_positions() now shows: {positions!r}")

        print(f"Closing contract_id={contract_id}...")
        close_result = None
        for attempt in range(5):
            try:
                close_result = await broker.close_position(contract_id)
                break
            except RuntimeError as e:
                if "Waiting for entry tick" not in str(e) or attempt == 4:
                    raise
                print(f"  Not ready yet ({e}) -- retrying in 2s...")
                await asyncio.sleep(2)
        print(f"Closed. Raw sell response: {close_result!r}")

        positions_after = await broker.open_positions()
        print(f"open_positions() after close: {positions_after!r}")
    finally:
        await broker.close()


async def cmd_close_position(args):
    """Manually closes one open contract by id -- e.g. to clean up a
    leftover position from an interrupted test-order run."""
    broker = DerivBroker()
    try:
        await broker.connect()
        result = await broker.close_position(args.contract_id)
        print(f"Closed. Raw sell response: {result!r}")
    finally:
        await broker.close()


def cmd_pause(args):
    set_paused(True, getattr(args, "reason", "") or "")
    print("Paused. The CFD bot will skip trading until resumed.")


def cmd_resume(_args):
    set_paused(False)
    print("Resumed. The CFD bot will trade again.")


def cmd_set_mode(args):
    """Sets the operating mode (defensive/normal/aggressive/recovery --
    see trading.cfd.operating_mode). Scales risk_per_trade and
    max_open_positions only -- never whether the bot trades at all
    (use pause/resume for that), and never past
    CFD_MAX_RISK_PER_TRADE_CEILING regardless of mode."""
    try:
        set_operating_mode(args.mode, args.reason or "")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Operating mode set to {args.mode}.")


def cmd_set_floor(args):
    """Sets the capital floor (virtual equity terms) -- see
    CfdRiskManager.capital_floor's docstring. No floor is set
    automatically; this is the only way one gets applied. Pick a number
    below your current virtual equity -- setting it AT your current
    equity means one ordinary loss immediately blocks all new entries
    until equity recovers back above it on its own (no open position to
    do that from, if you're flat, means it never will) -- use clear-floor
    to remove it if that happens."""
    set_capital_floor(args.amount)
    print(
        f"Capital floor set to {args.amount:.2f} (virtual equity terms). New entries stop while "
        f"equity is genuinely below this; existing positions still close normally."
    )


def cmd_clear_floor(_args):
    set_capital_floor(None)
    print("Capital floor cleared. No floor protection is active until you set-floor again.")


def cmd_exclude_instrument(args):
    exclude_instrument(args.instrument, args.reason or "")
    print(f"{args.instrument} excluded from new entries until included again. Existing open positions are unaffected.")


def cmd_include_instrument(args):
    include_instrument(args.instrument)
    print(f"{args.instrument} is eligible for new entries again.")


def main():
    parser = argparse.ArgumentParser(description="Manual control for the CFD/forex bot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status, is_async=True)

    sub.add_parser("performance").set_defaults(func=cmd_performance, is_async=False)

    sub.add_parser("paper-performance").set_defaults(func=cmd_paper_performance, is_async=False)

    sub.add_parser("failures").set_defaults(func=cmd_failures, is_async=False)

    sub.add_parser("manager-report").set_defaults(func=cmd_manager_report, is_async=False)

    sub.add_parser("list-strategies").set_defaults(func=cmd_list_strategies, is_async=False)

    promote_parser = sub.add_parser("promote-strategy")
    promote_parser.add_argument("name")
    promote_parser.add_argument("version")
    promote_parser.add_argument("state", help="Target lifecycle state: RESEARCH, CANDIDATE, VALIDATED, PAPER, ACTIVE, PAUSED, or RETIRED")
    promote_parser.add_argument("--reason", required=True)
    promote_parser.set_defaults(func=cmd_promote_strategy, is_async=False)

    list_symbols_parser = sub.add_parser("list-symbols")
    list_symbols_parser.add_argument("--filter", default="", help="Case-insensitive substring match against symbol/display_name/market/submarket")
    list_symbols_parser.set_defaults(func=cmd_list_symbols, is_async=True)

    pause_parser = sub.add_parser("pause")
    pause_parser.add_argument("--reason", default="", help="Why (e.g. 'macro risk: unscheduled Fed announcement')")
    pause_parser.set_defaults(func=cmd_pause, is_async=False)

    sub.add_parser("resume").set_defaults(func=cmd_resume, is_async=False)

    set_mode_parser = sub.add_parser("set-mode")
    set_mode_parser.add_argument("mode", choices=list(VALID_MODES))
    set_mode_parser.add_argument("--reason", default="")
    set_mode_parser.set_defaults(func=cmd_set_mode, is_async=False)

    floor_parser = sub.add_parser("set-floor")
    floor_parser.add_argument("amount", type=float)
    floor_parser.set_defaults(func=cmd_set_floor, is_async=False)

    sub.add_parser("clear-floor").set_defaults(func=cmd_clear_floor, is_async=False)

    exclude_parser = sub.add_parser("exclude-instrument")
    exclude_parser.add_argument("instrument")
    exclude_parser.add_argument("--reason", default="")
    exclude_parser.set_defaults(func=cmd_exclude_instrument, is_async=False)

    include_parser = sub.add_parser("include-instrument")
    include_parser.add_argument("instrument")
    include_parser.set_defaults(func=cmd_include_instrument, is_async=False)

    test_order_parser = sub.add_parser("test-order")
    test_order_parser.add_argument("--instrument", default=settings.cfd_instruments[0] if settings.cfd_instruments else "frxXAUUSD")
    test_order_parser.add_argument("--side", choices=["long", "short"], default="long")
    test_order_parser.add_argument("--multiplier", type=int, default=20, help="Deriv caps which multipliers are offered per instrument -- override if the default 20 isn't accepted.")
    test_order_parser.set_defaults(func=cmd_test_order, is_async=True)

    close_position_parser = sub.add_parser("close-position")
    close_position_parser.add_argument("contract_id", type=int)
    close_position_parser.set_defaults(func=cmd_close_position, is_async=True)

    args = parser.parse_args()
    if args.is_async:
        asyncio.run(args.func(args))
    else:
        args.func(args)


if __name__ == "__main__":
    main()

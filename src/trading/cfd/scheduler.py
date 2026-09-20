import asyncio
from datetime import datetime, timezone
from typing import Optional

from trading.cfd.broker import DerivBroker
from trading.cfd.capital import equity_for_account
from trading.cfd.decay_supervisor import run_autonomous_demotion
from trading.cfd.operating_mode import NORMAL, effective_max_open_positions, effective_risk_per_trade
from trading.cfd.paper_trading import run_paper_trading
from trading.cfd.regime import classify_regime
from trading.cfd.risk import CfdRiskManager
from trading.cfd.selector import select_for_entry
from trading.cfd.state import (
    get_daily_risk_tracking,
    list_open_trades,
    load_state,
    pop_open_trade,
    record_open_trade,
    set_broker_baseline,
    set_daily_risk_tracking,
)
from trading.cfd.strategy_registry import LifecycleState, get, list_by_state
from trading.cfd.trade_log import TradeRecord, load_trades, record_trade
from trading.config import settings
from trading.logging_utils import get_logger
from trading.strategy.base import Action

logger = get_logger(__name__)

GRANULARITY_SECONDS = 3600  # 1 hour -- see EmaCrossoverStrategy's docstring for why H1, not M15
CANDLE_COUNT = 200  # comfortably more than slow_span=34 + atr_window=14 warmup


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reconcile_closed_trades(tracked_open: dict, currently_open_ids: set[int], equity_now: float) -> list[TradeRecord]:
    """Detects contracts this system was tracking as open that are no
    longer open on Deriv's side -- closed by Deriv's own stop-loss/
    take-profit (or a manual scripts/cfd_cli.py close-position) between
    runs, rather than by this scheduler's own signal-exit logic below.

    Deriv's account balance only moves on a realized close or a new stake
    being paid, never on the unrealized/floating P&L of a still-open
    contract. So if exactly one tracked contract disappeared and nothing
    else touched the balance since it was opened, equity_now minus that
    trade's recorded equity_before is its exact realized P&L. With more
    than one simultaneous disappearance there's no way to split one
    combined balance change between them without an extra API call this
    project doesn't make yet (see docs/ARCHITECTURE_AUDIT.md) -- those are
    still logged, honestly, with pnl=None rather than a guessed split.
    """
    disappeared = {cid: meta for cid, meta in tracked_open.items() if int(cid) not in currently_open_ids}
    if not disappeared:
        return []

    records = []
    for contract_id, meta in disappeared.items():
        pnl = None
        equity_before = meta.get("equity_before")
        if len(disappeared) == 1 and equity_before is not None:
            pnl = round(equity_now - equity_before, 2)
        records.append(
            TradeRecord(
                contract_id=int(contract_id),
                instrument=meta.get("instrument", ""),
                strategy=meta.get("strategy", ""),
                side=meta.get("side", ""),
                entry_time=meta.get("entry_time", ""),
                exit_time=_now_iso(),
                entry_price=meta.get("entry_price", 0.0),
                stake=meta.get("stake", 0.0),
                risk_amount=meta.get("risk_amount", 0.0),
                pnl=pnl,
                equity_before=equity_before,
                equity_after=equity_now if pnl is not None else None,
                exit_reason="closed_externally (stop-loss/take-profit or manual close)",
                regime=meta.get("regime"),
            )
        )
    return records


def _resolve_exit_strategy_entry(meta: Optional[dict]):
    """Which registered strategy version should evaluate an existing open
    position's exit signal -- always the exact one that opened it (tagged
    "name@version" in its trade metadata, see record_open_trade below),
    never whatever's currently ACTIVE. A promotion or pause made after a
    position opened must not retroactively change how that position gets
    managed.

    Falls back to the sole ACTIVE strategy, if there's exactly one, only
    for a position opened before this tagging existed (meta missing or
    its tag no longer resolves) -- best-effort so a legacy position can
    still be managed rather than orphaned, never a substitute for the
    normal per-trade tagging."""
    if meta and meta.get("strategy"):
        name, _, version = meta["strategy"].partition("@")
        entry = get(name, version)
        if entry is not None:
            return entry
    active_now = list_by_state(LifecycleState.ACTIVE)
    return active_now[0] if len(active_now) == 1 else None


async def run_once():
    """Evaluate each configured CFD instrument on its latest completed H1
    candle and place/close orders accordingly. Meant to run roughly
    hourly during market hours via a scheduled GitHub Actions workflow --
    see .github/workflows/cfd-trading.yml.

    Confirmed end-to-end against the real Deriv API (connect, buy,
    portfolio read, sell) -- see src/trading/cfd/broker.py's docstring.

    Every risk/sizing decision here uses *virtual* equity on a demo
    account, never the raw ~$10,000 Deriv demo balance -- see
    trading.cfd.capital and docs/VISION.md's "Capital model" section.

    The daily-loss circuit breaker's start-of-day equity and halted flag
    are persisted (trading.cfd.state.get/set_daily_risk_tracking) and fed
    into CfdRiskManager explicitly, keyed off the current UTC calendar
    date -- each run is a fresh process (GitHub Actions), so without this
    the breaker would silently reset every single run and never actually
    see a full day's accumulated loss. capital_floor is never set
    automatically; it stays whatever `cfd_cli.py set-floor`/`clear-floor`
    last left it (None by default -- no floor protection until you
    explicitly choose one), because auto-setting it to the exact starting
    balance on day one meant a single ordinary loss on a small account
    permanently blocked all new entries with no way to recover.

    risk_per_trade and max_open_positions are scaled by the current
    Operating Mode (trading.cfd.operating_mode, set via
    `cfd_cli.py set-mode`) before CfdRiskManager ever sees them -- still
    bounded by CFD_MAX_RISK_PER_TRADE_CEILING, an absolute ceiling no
    mode may cross.

    Which strategy opens a NEW position is decided per instrument, per
    run, by the Strategy Selector (trading.cfd.selector.select_for_entry)
    matching the instrument's current regime (trading.cfd.regime) against
    the Strategy Registry's ACTIVE entries -- not a single hardcoded or
    globally-fixed strategy. No ACTIVE strategy suited to the current
    regime is an explicit NO TRADE, not a guess. An already-open position
    is always managed by the exact strategy version that opened it (see
    _resolve_exit_strategy_entry), regardless of what's ACTIVE now.

    Every PAPER-state strategy also gets evaluated on the same candles
    (trading.cfd.paper_trading.run_paper_trading), simulating fills
    without ever placing a real order -- see that module's docstring.
    Paper trading stops whenever the bot is paused too, same as real
    trading -- simplest, safest default; nothing (real or simulated)
    opens a new position while a human has explicitly halted the bot.

    Before any of the above: trading.cfd.decay_supervisor.
    run_autonomous_demotion() checks every ACTIVE strategy against
    Failure Analysis's degradation signal and pauses any that qualify,
    with no human approval needed -- per docs/VISION.md's "Autonomy
    boundaries," the AI may act on its own to reduce risk (demote,
    pause, go flat), never to increase it or promote something.
    """
    state = load_state()
    if state.get("paused"):
        logger.info("CFD bot is paused (state/cfd_bot_state.json) -- skipping this run.")
        return

    # Autonomous demotion (docs/VISION.md's "Autonomy boundaries"): any
    # ACTIVE strategy Failure Analysis flags as decayed is paused right
    # here, before this run even looks at which strategies are ACTIVE --
    # no human approval needed for a risk-reducing action, only for the
    # reverse. Cheap and local (no network), so it runs before the broker
    # connection below.
    for demotion in run_autonomous_demotion(load_trades()):
        logger.warning("%s -- %s", demotion["strategy"], demotion["reason"])

    if not list_by_state(LifecycleState.ACTIVE):
        raise RuntimeError("No strategy is registered as ACTIVE -- nothing to trade. See `cfd_cli.py list-strategies`.")

    broker = DerivBroker()
    try:
        account = await broker.connect()
        account_type = account.get("account_type")
        broker_balance = await broker.account_equity()

        broker_baseline = state.get("broker_baseline")
        if account_type == "demo" and broker_baseline is None:
            set_broker_baseline(broker_balance)
            broker_baseline = broker_balance
            logger.info(
                "First run: broker baseline recorded at %.2f (raw demo balance) -- "
                "virtual equity now tracks P&L from here, rebased onto %.2f, not the raw balance.",
                broker_balance, settings.cfd_virtual_starting_capital,
            )

        equity = equity_for_account(broker_balance, account_type, broker_baseline, settings.cfd_virtual_starting_capital)

        # No floor is set automatically -- capital_floor stays None (no
        # protection) until explicitly set via `cfd_cli.py set-floor`,
        # same opt-in pattern as the stock system's cli.py. Auto-setting
        # it to the exact starting balance on day one used to be the
        # default here, but on a small account a single ordinary loss
        # drops equity below a floor set that tight -- and with no
        # set-floor/clear-floor command to recover from it, that
        # silently halted all new entries forever. Set one deliberately,
        # below your actual starting balance, once you've decided how
        # much cushion you want to protect.
        capital_floor = state.get("capital_floor")

        today = datetime.now(timezone.utc).date().isoformat()
        daily_tracking = get_daily_risk_tracking()
        if daily_tracking.get("date") == today:
            daily_start_equity = daily_tracking.get("start_equity")
            initially_halted = daily_tracking.get("halted", False)
        else:
            daily_start_equity = equity
            initially_halted = False

        mode = state.get("operating_mode", NORMAL)
        effective_risk = effective_risk_per_trade(mode, settings.cfd_risk_per_trade)
        effective_max_positions = effective_max_open_positions(mode, settings.cfd_max_open_positions)
        if mode != NORMAL:
            logger.info(
                "Operating mode=%s: risk_per_trade %.4f -> %.4f, max_open_positions %d -> %d (%s)",
                mode, settings.cfd_risk_per_trade, effective_risk,
                settings.cfd_max_open_positions, effective_max_positions,
                state.get("operating_mode_reason") or "no reason given",
            )

        risk = CfdRiskManager(
            equity=equity,
            risk_per_trade=effective_risk,
            max_open_positions=effective_max_positions,
            max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
            capital_floor=capital_floor,
            min_stake=settings.cfd_min_stake,
            daily_start_equity=daily_start_equity,
            initially_halted=initially_halted,
        )
        if risk.halted:
            logger.info("Daily loss limit already breached today (%.2f%% halt) -- no new entries this run.", settings.cfd_max_daily_loss_pct * 100)
        if risk.below_floor():
            logger.info("Equity %.2f is below the capital floor %.2f -- no new entries this run.", equity, capital_floor)

        # Trade Database reconciliation: log anything Deriv closed on its
        # own (stop-loss/take-profit, or a manual close) since the last
        # run, before this run does anything else.
        tracked_open = list_open_trades()
        currently_open_ids = await broker.open_contract_ids()
        for record in _reconcile_closed_trades(tracked_open, currently_open_ids, equity):
            record_trade(record)
            pop_open_trade(record.contract_id)
            logger.info(
                "%s: reconciled externally-closed contract %d (pnl=%s)",
                record.instrument, record.contract_id, record.pnl,
            )

        excluded = state.get("excluded_instruments") or {}
        open_positions = await broker.open_positions()

        for instrument in settings.cfd_instruments:
            if instrument in excluded:
                logger.debug("%s: excluded (%s)", instrument, excluded[instrument] or "no reason given")
                continue

            bars = await broker.get_candles(instrument, granularity_seconds=GRANULARITY_SECONDS, count=CANDLE_COUNT)
            if len(bars) < 2:
                logger.debug("%s: not enough candles yet", instrument)
                continue

            regime = classify_regime(bars, settings.cfd_regime_adx_window, settings.cfd_regime_trend_threshold)

            # Paper Trading runs independently of the real position below
            # -- every PAPER-state strategy gets evaluated on this same
            # instrument/candles/regime regardless of what's happening
            # with real (or virtual-real) capital.
            run_paper_trading(instrument, bars, regime)

            position = open_positions.get(instrument)
            in_position = position["side"] if position else None

            if in_position is not None:
                contract_id = position["contract_id"]
                meta = tracked_open.get(str(contract_id))  # peek only -- don't remove until actually closing
                exit_entry = _resolve_exit_strategy_entry(meta)
                if exit_entry is None:
                    logger.warning(
                        "%s: can't determine which strategy opened contract %d (no tracked metadata, and not "
                        "exactly one ACTIVE strategy to fall back to) -- leaving it to Deriv's own stop-loss/"
                        "take-profit and reconciliation next run.",
                        instrument, contract_id,
                    )
                    continue

                exit_strategy = exit_entry.build()
                prepared = exit_strategy.prepare(bars)
                row, prev_row = prepared.iloc[-1], prepared.iloc[-2]
                signal = exit_strategy.signal_for_row(instrument, row, prev_row, in_position)

                is_exit = (in_position == "long" and signal.action == Action.SELL) or (
                    in_position == "short" and signal.action == Action.BUY
                )
                if not is_exit:
                    continue

                logger.info("%s: closing %s position (%s)", instrument, in_position, signal.reason)
                pop_open_trade(contract_id)
                equity_before = risk.equity
                await broker.close_position(contract_id)
                new_balance = await broker.account_equity()
                new_equity = equity_for_account(
                    new_balance, account_type, broker_baseline, settings.cfd_virtual_starting_capital
                )
                pnl = round(new_equity - equity_before, 2)
                risk.register_close(pnl)
                equity = new_equity
                if meta:
                    record_trade(
                        TradeRecord(
                            contract_id=contract_id,
                            instrument=instrument,
                            strategy=meta.get("strategy", f"{exit_entry.name}@{exit_entry.version}"),
                            side=in_position,
                            entry_time=meta.get("entry_time", ""),
                            exit_time=_now_iso(),
                            entry_price=meta.get("entry_price", 0.0),
                            stake=meta.get("stake", 0.0),
                            risk_amount=meta.get("risk_amount", 0.0),
                            exit_price=signal.price,
                            pnl=pnl,
                            equity_before=equity_before,
                            equity_after=new_equity,
                            exit_reason="signal_exit: " + signal.reason,
                            regime=meta.get("regime"),
                        )
                    )
                else:
                    logger.warning(
                        "%s: closed contract %d with no tracked entry metadata "
                        "(opened before trade logging existed) -- pnl not logged to the trade database.",
                        instrument, contract_id,
                    )
                continue

            # Flat -- decide whether to open a new position, per the
            # Strategy Selector: current regime matched against whichever
            # strategy (if any) is ACTIVE for it. No match is NO TRADE.
            entry_candidate = select_for_entry(regime)
            if entry_candidate is None:
                logger.debug("%s: NO TRADE (regime=%s, no ACTIVE strategy suited to it)", instrument, regime)
                continue

            strategy = entry_candidate.build()
            prepared = strategy.prepare(bars)
            row, prev_row = prepared.iloc[-1], prepared.iloc[-2]
            signal = strategy.signal_for_row(instrument, row, prev_row, None)

            if signal.action == Action.HOLD:
                logger.debug("%s: %s", instrument, signal.reason)
                continue
            if len(open_positions) >= effective_max_positions:
                logger.info("Skipping %s: max open positions reached", instrument)
                continue

            stake, stop_loss_amount, take_profit_amount = risk.stake_and_limits(
                signal.price, signal.stop_price, signal.take_profit_price
            )
            if stake <= 0:
                logger.info("Skipping %s: stake computed as 0 (risk limit, halt, or below Deriv's minimum stake)", instrument)
                continue

            side = "long" if signal.action == Action.BUY else "short"
            strategy_tag = f"{entry_candidate.name}@{entry_candidate.version}"
            logger.info(
                "%s %s stake=%.2f (stop-loss $%.2f, take-profit $%.2f) -- regime=%s, %s (%s)",
                side.upper(), instrument, stake, stop_loss_amount, take_profit_amount, regime, signal.reason, strategy_tag,
            )
            result = await broker.submit_multiplier_order(
                instrument, side, stake, risk.multiplier, stop_loss_amount, take_profit_amount
            )
            contract_id = result.get("buy", {}).get("contract_id")
            open_positions[instrument] = {"contract_id": contract_id, "side": side}
            if contract_id is not None:
                risk.register_open()
                record_open_trade(
                    contract_id,
                    {
                        "instrument": instrument,
                        "strategy": strategy_tag,
                        "side": side,
                        "entry_time": _now_iso(),
                        "entry_price": signal.price,
                        "stake": stake,
                        "risk_amount": stop_loss_amount,
                        "equity_before": risk.equity,
                        "regime": regime,
                    },
                )

        set_daily_risk_tracking(today, risk.daily_start_equity, risk.halted)
    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(run_once())

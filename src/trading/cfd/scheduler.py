import asyncio
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from trading.cfd.broker import DerivBroker
from trading.cfd.capital import equity_for_account
from trading.cfd.decay_supervisor import run_autonomous_demotion
from trading.cfd.exit_manager import (
    TrailingStopState,
    split_stake_for_partial_close,
    trailing_stop_hit,
    update_trailing_stop,
)
from trading.cfd.operating_mode import NORMAL, effective_max_open_positions, effective_risk_per_trade
from trading.cfd.paper_trading import run_paper_trading
from trading.cfd.portfolio_allocator import compute_allocations, risk_scale_factor
from trading.cfd.portfolio_risk import (
    OpenRiskPosition,
    PortfolioRiskCeilings,
    check_new_position,
    thesis_key as compute_thesis_key,
)
from trading.cfd.regime import classify_regime
from trading.cfd.risk import CfdRiskManager
from trading.cfd.selector import select_for_entry
from trading.cfd.state import (
    clear_pending_entry,
    exclude_instrument,
    get_daily_risk_tracking,
    get_pending_entries,
    list_open_trades,
    load_state,
    pop_open_trade,
    record_open_trade,
    set_broker_baseline,
    set_daily_risk_tracking,
    set_pending_entry,
)
from trading.cfd.strategy_registry import LifecycleState, get, list_by_state
from trading.cfd.trade_log import TradeRecord, load_trades, record_trade
from trading.config import settings
from trading.logging_utils import get_logger
from trading.strategy.base import Action

logger = get_logger(__name__)

GRANULARITY_SECONDS = 3600  # 1 hour -- see EmaCrossoverStrategy's docstring for why H1, not M15
CANDLE_COUNT = 200  # comfortably more than slow_span=34 + atr_window=14 warmup,
# and more than regime.py's default volatility_lookback=100 + atr_window=14


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reconcile_closed_trades(tracked_open: dict, currently_open_ids: set[int], equity_now: float) -> list[TradeRecord]:
    """Detects contracts this system was tracking as open that are no
    longer open on Deriv's side -- closed by Deriv's own stop-loss/
    take-profit (or a manual scripts/cfd_cli.py close-position) between
    runs, rather than by this scheduler's own signal-exit/trailing-stop
    logic below.

    Deriv's account balance only moves on a realized close or a new stake
    being paid, never on the unrealized/floating P&L of a still-open
    contract. So if exactly one tracked contract disappeared and nothing
    else touched the balance since it was opened, equity_now minus that
    trade's recorded equity_before is its exact realized P&L. With more
    than one simultaneous disappearance there's no way to split one
    combined balance change between them without an extra API call this
    project doesn't make yet (see docs/ARCHITECTURE_AUDIT.md) -- those are
    still logged, honestly, with pnl=None rather than a guessed split.
    Two legs of one entry (see exit_manager.split_stake_for_partial_close)
    disappearing in the same run is exactly this "more than one" case --
    e.g. a "scalp" leg's Deriv-side take-profit firing the same hour a
    "runner" leg's stop is hit externally would both land here unpriced.
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
                thesis_key=meta.get("thesis_key"),
                leg=meta.get("leg"),
            )
        )
    return records


def _reconcile_unknown_positions(
    positions_by_instrument: dict[str, list[dict]], tracked_open: dict, pending_entries: dict
) -> tuple[list[tuple[int, dict]], list[dict]]:
    """Splits every currently-open contract with no local metadata
    (`tracked_open`) into two buckets:

    adoptions: (contract_id, leg_meta) pairs to record_open_trade() --
    contracts matching a *pending* entry (trading.cfd.state.
    set_pending_entry, written right before this bot's own
    submit_multiplier_order calls) from a run that crashed between
    submitting the order and its state-file commit ever landing (each
    run's local state.json is only committed to git in a separate,
    later workflow step -- see .github/workflows/cfd-trading.yml). This
    recovers the strategy/thesis/risk_amount attribution that would
    otherwise be lost, closing Revision 3 gap #9's attribution window.

    foreign: contracts with NO matching pending entry either -- never
    opened by this bot's own tracked intent at all (a manual trade, or
    an unrelated script hitting the same account). Never silently
    absorbed into this bot's own strategy/thesis attribution -- closes
    Revision 3 gap #8. The caller logs these loudly and excludes the
    instrument from new entries until a human investigates; their
    balance impact still reaches virtual equity (which is derived from
    the raw broker balance delta, not per-trade attribution -- see
    docs/ARCHITECTURE_AUDIT.md for why that part isn't solvable without
    a deeper per-trade balance API this project doesn't have)."""
    adoptions: list[tuple[int, dict]] = []
    foreign: list[dict] = []
    for instrument, legs in positions_by_instrument.items():
        unknown_legs = [leg for leg in legs if str(leg["contract_id"]) not in tracked_open]
        if not unknown_legs:
            continue
        pending_legs = list(pending_entries.get(instrument, {}).get("legs", []))
        for leg in unknown_legs:
            if pending_legs:
                adoptions.append((leg["contract_id"], pending_legs.pop(0)))
            else:
                foreign.append({"contract_id": leg["contract_id"], "instrument": instrument, "side": leg["side"]})
    return adoptions, foreign


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
    mode may cross. max_open_positions counts distinct INSTRUMENTS with
    at least one leg open, not raw contracts -- a partial-close split
    (see below) never silently doubles this count.

    Which strategy opens a NEW position is decided per instrument, per
    run, by the Strategy Selector (trading.cfd.selector.select_for_entry)
    matching the instrument's current regime (trading.cfd.regime) against
    the Strategy Registry's ACTIVE entries -- not a single hardcoded or
    globally-fixed strategy. No ACTIVE strategy suited to the current
    regime is an explicit NO TRADE, not a guess. An already-open position
    is always managed by the exact strategy version that opened it (see
    _resolve_exit_strategy_entry), regardless of what's ACTIVE now.

    More than one ACTIVE strategy can be suited to the same regime --
    trading.cfd.portfolio_allocator.compute_allocations() weights each by
    recent performance once per run, the Selector picks among matches by
    that weight, and the winning entry's stake is itself sized by its
    weight relative to the others (capped so no strategy's risk ever
    exceeds what risk_per_trade alone would already allow -- allocation
    only ever redistributes the existing budget, never raises it). This
    is docs/VISION.md's revised "Portfolio / Allocation Decision" stage,
    not a single-winner selector.

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

    Every new entry also passes trading.cfd.portfolio_risk.
    check_new_position() -- the Portfolio Risk Governor docs/VISION.md's
    Revision 3 "Risk model" requires: per-thesis, correlated,
    total-portfolio, and leverage/exposure ceilings, checked against
    every position this system currently has open (persisted across
    runs, not just ones opened this run), rejecting (SKIP TRADE) an
    otherwise-valid entry purely because the PORTFOLIO is already at its
    limit -- never satisfied by max_open_positions' raw position count
    alone. See that module's docstring for the ceilings and the
    (deliberately static, not live-computed) correlation model.

    An approved entry is then handed to trading.cfd.exit_manager for
    Adaptive Exit Management (docs/VISION.md's Revision 3 exit
    philosophy): rather than one contract with a small fixed take-profit
    that caps every winner, it's split into a "scalp" leg (a fraction of
    the stake, keeping the strategy's own normal target -- locks in some
    profit early) and a "runner" leg (the remainder, no effective fixed
    target -- managed by a trailing stop that only ever tightens,
    computed fresh from the latest ATR every run, plus the strategy's own
    signal exit). If the split would put either leg below CFD_MIN_STAKE,
    a single full-stake "runner" leg is opened instead -- never the old
    behavior of a single leg with a small fixed take-profit. Both legs
    share the same thesis_key and both were already included as one
    combined unit in the Portfolio Risk Governor check above.

    Before any new entry is submitted, its intent is recorded
    (trading.cfd.state.set_pending_entry) and cleared again right after --
    if this process crashes in between, or its state-file commit never
    lands (a separate, later workflow step), the next run's
    _reconcile_unknown_positions() recovers full attribution for
    whichever leg(s) actually went through, rather than losing it.
    Separately, ANY contract open on Deriv with no local tracked_open
    metadata and no matching pending entry is treated as a genuinely
    foreign position -- never silently absorbed into this bot's own
    strategy/thesis attribution; its instrument is auto-excluded from
    new entries (a risk-reducing action, no human approval needed) until
    a human investigates. Both close docs/VISION.md's Revision 3
    execution-realism requirements.
    """
    state = load_state()
    if state.get("paused"):
        logger.info("CFD bot is paused (state/cfd_bot_state.json) -- skipping this run.")
        return

    trades = load_trades()

    # Autonomous demotion (docs/VISION.md's "Autonomy boundaries"): any
    # ACTIVE strategy Failure Analysis flags as decayed is paused right
    # here, before this run even looks at which strategies are ACTIVE --
    # no human approval needed for a risk-reducing action, only for the
    # reverse. Cheap and local (no network), so it runs before the broker
    # connection below.
    for demotion in run_autonomous_demotion(trades):
        logger.warning("%s -- %s", demotion["strategy"], demotion["reason"])

    active_entries = list_by_state(LifecycleState.ACTIVE)
    if not active_entries:
        raise RuntimeError("No strategy is registered as ACTIVE -- nothing to trade. See `cfd_cli.py list-strategies`.")

    # Portfolio / Allocation Decision (docs/VISION.md's revised pipeline):
    # every ACTIVE strategy gets a weight (trading.cfd.portfolio_allocator)
    # from its own recent performance -- used below both to pick among
    # several regime-suited strategies for one instrument's entry, and to
    # scale that entry's risk relative to the others. Computed once per
    # run on the roster left standing after autonomous demotion above.
    allocations = compute_allocations(trades, active_entries)
    n_active = len(active_entries)
    if n_active > 1:
        logger.debug("Portfolio allocation this run: %s", allocations)

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
            stake_safety_margin=settings.cfd_stake_safety_margin,
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
        reconciled_ids: set[int] = set()
        for record in _reconcile_closed_trades(tracked_open, currently_open_ids, equity):
            record_trade(record)
            pop_open_trade(record.contract_id)
            reconciled_ids.add(record.contract_id)
            logger.info(
                "%s: reconciled externally-closed contract %d (pnl=%s)",
                record.instrument, record.contract_id, record.pnl,
            )

        # open_positions_list(), not open_positions() -- a partial-close
        # split (below) can legitimately leave two simultaneous contracts
        # ("scalp" and "runner") open on the SAME instrument, which
        # open_positions()'s symbol-collapsed dict would silently hide
        # one of. See broker.py's docstrings on both methods.
        positions_by_instrument: dict[str, list[dict]] = {}
        for p in await broker.open_positions_list():
            positions_by_instrument.setdefault(p["instrument"], []).append(p)

        # Idempotency / attribution recovery + foreign-position detection
        # (docs/VISION.md's Revision 3 execution-realism requirements):
        # any contract open on Deriv with no local tracked_open metadata
        # either matches a pending entry from a run that crashed between
        # submitting an order and its state-file commit ever landing
        # (adopted -- attribution recovered, see _reconcile_unknown_
        # positions' docstring) or it's genuinely foreign -- never opened
        # by this bot's own tracked intent. A foreign contract is never
        # silently absorbed into this bot's strategy/thesis attribution;
        # its instrument is auto-excluded from new entries (the existing,
        # already-audited excluded_instruments mechanism -- a
        # risk-reducing action, no human approval needed) until a human
        # investigates and runs `cfd_cli.py include-instrument` again.
        pending_entries = get_pending_entries()
        adoptions, foreign = _reconcile_unknown_positions(positions_by_instrument, tracked_open, pending_entries)
        for contract_id, leg_meta in adoptions:
            record_open_trade(contract_id, leg_meta)
            tracked_open[str(contract_id)] = leg_meta
            logger.warning(
                "%s: recovered attribution for contract %d from a pending entry interrupted last run.",
                leg_meta.get("instrument", ""), contract_id,
            )
        for pending_instrument in pending_entries:
            clear_pending_entry(pending_instrument)
        excluded = dict(state.get("excluded_instruments") or {})
        for f in foreign:
            reason = f"foreign position detected: contract {f['contract_id']} was never opened by this bot -- investigate, then `include-instrument` to resume"
            exclude_instrument(f["instrument"], reason)
            excluded[f["instrument"]] = reason
            logger.warning(
                "FOREIGN POSITION: %s contract %d is open on Deriv but was never opened by this bot's tracked "
                "intent -- not attributed to any strategy/thesis, instrument auto-excluded from new entries. "
                "Virtual equity still reflects its balance impact (derived from the raw broker balance delta, "
                "not per-trade attribution). Investigate manually.",
                f["instrument"], f["contract_id"],
            )

        # Portfolio Risk Governor snapshot: every position this system
        # currently has open, across every run so far (not just ones
        # opened this run) -- rebuilt fresh each run from the same
        # persisted state.list_open_trades() _resolve_exit_strategy_entry
        # already trusts, minus anything just reconciled away above, plus
        # anything just adopted above. Mutated in place below as
        # positions open/close within this run's own loop, so later
        # instruments see the up-to-date total.
        open_risk_positions = [
            OpenRiskPosition(
                contract_id=int(cid),
                instrument=meta.get("instrument", ""),
                side=meta.get("side", ""),
                risk_amount=meta.get("risk_amount", 0.0),
                notional=meta.get("stake", 0.0) * meta.get("multiplier", 0.0),
            )
            for cid, meta in tracked_open.items()
            if int(cid) not in reconciled_ids
        ]
        risk_ceilings = PortfolioRiskCeilings(
            max_thesis_risk_pct=settings.cfd_max_thesis_risk_pct,
            max_correlated_risk_pct=settings.cfd_max_correlated_risk_pct,
            max_portfolio_risk_pct=settings.cfd_max_portfolio_risk_pct,
            max_exposure_multiple=settings.cfd_max_exposure_multiple,
        )

        for instrument in settings.cfd_instruments:
            if instrument in excluded:
                logger.debug("%s: excluded (%s)", instrument, excluded[instrument] or "no reason given")
                continue

            bars = await broker.get_candles(instrument, granularity_seconds=GRANULARITY_SECONDS, count=CANDLE_COUNT)
            if len(bars) < 2:
                logger.debug("%s: not enough candles yet", instrument)
                continue

            regime = classify_regime(
                bars,
                settings.cfd_regime_adx_window,
                settings.cfd_regime_trend_threshold,
                atr_window=settings.cfd_regime_atr_window,
                volatility_lookback=settings.cfd_regime_volatility_lookback,
                unstable_volatility_ratio=settings.cfd_regime_unstable_volatility_ratio,
            )

            # Paper Trading runs independently of the real position below
            # -- every PAPER-state strategy gets evaluated on this same
            # instrument/candles/regime regardless of what's happening
            # with real (or virtual-real) capital.
            run_paper_trading(instrument, bars, regime)

            legs = positions_by_instrument.get(instrument, [])
            if legs:
                # Every leg still open for one instrument always shares
                # the same side and strategy tag -- they can only ever
                # come from ONE entry decision, since a new entry is
                # never opened for an instrument that already has a leg
                # open (see the "continue" at the end of this branch).
                first_meta = tracked_open.get(str(legs[0]["contract_id"]))
                exit_entry = _resolve_exit_strategy_entry(first_meta)
                if exit_entry is None:
                    logger.warning(
                        "%s: can't determine which strategy opened this position (no tracked metadata, and not "
                        "exactly one ACTIVE strategy to fall back to) -- leaving it to Deriv's own stop-loss/"
                        "take-profit and reconciliation next run.",
                        instrument,
                    )
                    continue

                in_position = legs[0]["side"]
                exit_strategy = exit_entry.build()
                prepared = exit_strategy.prepare(bars)
                row, prev_row = prepared.iloc[-1], prepared.iloc[-2]
                signal = exit_strategy.signal_for_row(instrument, row, prev_row, in_position)
                is_exit_signal = (in_position == "long" and signal.action == Action.SELL) or (
                    in_position == "short" and signal.action == Action.BUY
                )
                current_atr = row.get("atr") if hasattr(row, "get") else None
                current_atr = 0.0 if current_atr is None or pd.isna(current_atr) else float(current_atr)

                for leg in legs:
                    contract_id = leg["contract_id"]
                    meta = tracked_open.get(str(contract_id))
                    leg_tag = (meta or {}).get("leg")

                    close_reason = None
                    exit_price = row["close"]
                    if is_exit_signal:
                        close_reason = "signal_exit: " + signal.reason
                        exit_price = signal.price
                    elif leg_tag == "runner" and meta and meta.get("trailing_stop") and current_atr > 0:
                        trailing_state = TrailingStopState.from_dict(meta["trailing_stop"])
                        updated_state = update_trailing_stop(
                            trailing_state,
                            current_price=row["close"],
                            current_atr=current_atr,
                            activation_r_multiple=settings.cfd_trailing_activation_r_multiple,
                            trail_atr_multiple=settings.cfd_trailing_atr_multiple,
                        )
                        if trailing_stop_hit(updated_state, bar_low=row["low"], bar_high=row["high"]):
                            close_reason = f"trailing_stop_hit (stop={updated_state.current_stop_price:.5f})"
                        else:
                            meta["trailing_stop"] = updated_state.as_dict()
                            record_open_trade(contract_id, meta)  # persist the ratcheted stop for next run

                    if close_reason is None:
                        continue

                    logger.info(
                        "%s: closing %s leg (contract %d, %s position) -- %s",
                        instrument, leg_tag or "untagged", contract_id, in_position, close_reason,
                    )
                    pop_open_trade(contract_id)
                    open_risk_positions = [p for p in open_risk_positions if p.contract_id != contract_id]
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
                                exit_price=exit_price,
                                pnl=pnl,
                                equity_before=equity_before,
                                equity_after=new_equity,
                                exit_reason=close_reason,
                                regime=meta.get("regime"),
                                thesis_key=meta.get("thesis_key"),
                                leg=leg_tag,
                            )
                        )
                    else:
                        logger.warning(
                            "%s: closed contract %d with no tracked entry metadata "
                            "(opened before trade logging existed) -- pnl not logged to the trade database.",
                            instrument, contract_id,
                        )

                # At least one leg was open for this instrument -- never
                # also evaluate a new entry the same run, regardless of
                # how many of its legs just closed above.
                continue

            # Flat -- decide whether to open a new position, per the
            # Strategy Selector: current regime matched against whichever
            # strategy (if any) is ACTIVE for it. No match is NO TRADE.
            # Several ACTIVE strategies may match; the allocator's weights
            # (computed above) break the tie.
            entry_candidate = select_for_entry(regime, allocations)
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
            if len(positions_by_instrument) >= effective_max_positions:
                logger.info("Skipping %s: max open positions reached", instrument)
                continue

            strategy_tag = f"{entry_candidate.name}@{entry_candidate.version}"
            weight = allocations.get(strategy_tag, 1.0 / n_active if n_active else 1.0)
            risk_per_trade_override = effective_risk * risk_scale_factor(weight, n_active)

            stake, stop_loss_amount, take_profit_amount = risk.stake_and_limits(
                signal.price, signal.stop_price, signal.take_profit_price,
                risk_per_trade_override=risk_per_trade_override,
            )
            if stake <= 0:
                logger.info("Skipping %s: stake computed as 0 (risk limit, halt, or below Deriv's minimum stake)", instrument)
                continue

            side = "long" if signal.action == Action.BUY else "short"
            new_notional = stake * risk.multiplier
            rejection = check_new_position(
                open_risk_positions, instrument, side, stop_loss_amount, new_notional, risk.equity, risk_ceilings,
            )
            if rejection is not None:
                logger.info("Skipping %s: Portfolio Risk Governor rejected this entry -- %s", instrument, rejection)
                continue

            # Adaptive Exit Management (trading.cfd.exit_manager, see
            # run_once()'s docstring): split into "scalp" (keeps the
            # strategy's own normal target, locks in profit early) and
            # "runner" (no effective fixed target -- trailing-stop
            # managed) legs, or a single full-stake "runner" leg if
            # splitting would put either leg below CFD_MIN_STAKE.
            split = split_stake_for_partial_close(
                stake, stop_loss_amount, take_profit_amount,
                settings.cfd_partial_close_fraction, settings.cfd_min_stake, settings.cfd_runner_backstop_multiple,
            )
            if split is not None:
                scalp, runner = split
                legs_to_open = [("scalp", scalp), ("runner", runner)]
            else:
                full_runner_tp = round(take_profit_amount * settings.cfd_runner_backstop_multiple, 2)
                legs_to_open = [
                    ("runner", {"stake": stake, "risk_amount": stop_loss_amount, "take_profit_amount": full_runner_tp})
                ]

            entry_thesis_key = compute_thesis_key(instrument, side)
            entry_time = _now_iso()
            leg_metas = []
            for leg_tag, leg_terms in legs_to_open:
                leg_meta = {
                    "instrument": instrument,
                    "strategy": strategy_tag,
                    "side": side,
                    "entry_time": entry_time,
                    "entry_price": signal.price,
                    "stake": leg_terms["stake"],
                    "risk_amount": leg_terms["risk_amount"],
                    "multiplier": risk.multiplier,
                    "thesis_key": entry_thesis_key,
                    "equity_before": risk.equity,
                    "regime": regime,
                    "leg": leg_tag,
                }
                if leg_tag == "runner":
                    leg_meta["trailing_stop"] = TrailingStopState(
                        entry_price=signal.price, initial_stop_price=signal.stop_price, side=side,
                    ).as_dict()
                leg_metas.append((leg_tag, leg_terms, leg_meta))

            # Record intent BEFORE submitting any order -- if this
            # process crashes partway through, or its state-file commit
            # never lands (a separate, later workflow step -- see
            # .github/workflows/cfd-trading.yml), the next run's
            # _reconcile_unknown_positions() recovers full attribution
            # for whichever leg(s) actually went through instead of
            # losing it or misflagging them as foreign.
            set_pending_entry(instrument, {"legs": [lm for _, _, lm in leg_metas]})

            opened_legs = []
            for leg_tag, leg_terms, leg_meta in leg_metas:
                leg_stake, leg_risk, leg_tp = leg_terms["stake"], leg_terms["risk_amount"], leg_terms["take_profit_amount"]
                logger.info(
                    "%s %s leg=%s stake=%.2f (stop-loss $%.2f, take-profit $%.2f) -- regime=%s, %s (%s)",
                    side.upper(), instrument, leg_tag, leg_stake, leg_risk, leg_tp, regime, signal.reason, strategy_tag,
                )
                result = await broker.submit_multiplier_order(instrument, side, leg_stake, risk.multiplier, leg_risk, leg_tp)
                contract_id = result.get("buy", {}).get("contract_id")
                if contract_id is None:
                    logger.warning("%s: leg=%s order submitted but no contract_id returned -- not tracked.", instrument, leg_tag)
                    continue

                record_open_trade(contract_id, leg_meta)
                open_risk_positions.append(
                    OpenRiskPosition(
                        contract_id=contract_id, instrument=instrument, side=side,
                        risk_amount=leg_risk, notional=leg_stake * risk.multiplier,
                    )
                )
                opened_legs.append({"contract_id": contract_id, "side": side})

            # Every leg either succeeded (tracked_open now has it, via
            # record_open_trade above) or failed outright (nothing to
            # adopt) -- either way this run's intent is resolved, so the
            # pending marker is cleared now rather than left for next
            # run's reconciliation to puzzle back out.
            clear_pending_entry(instrument)
            if opened_legs:
                risk.register_open()
                positions_by_instrument[instrument] = opened_legs

        set_daily_risk_tracking(today, risk.daily_start_equity, risk.halted)
    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(run_once())

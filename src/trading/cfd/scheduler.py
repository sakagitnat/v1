import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from trading.cfd.auto_mode import choose_autonomous_mode
from trading.cfd.broker import DerivBroker
from trading.cfd.quota import commit_close as commit_quota_close
from trading.cfd.decision_log import record_decision
from trading.cfd.incident_log import record_incident
from trading.cfd.lab_collector import collect_lab_observations
from trading.cfd.capital import equity_for_account
from trading.cfd.decay_supervisor import run_autonomous_demotion
from trading.cfd.drawdown_monitor import (
    NORMAL as DRAWDOWN_NORMAL,
    DrawdownThresholds,
    classify_drawdown_tier,
    drawdown_risk_multiplier,
)
from trading.cfd.event_blackout import in_blackout_window
from trading.cfd.event_calendar import EVENTS as OFFICIAL_EVENTS
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
from trading.cfd.smoothed_equity import update_high_water_mark, update_smoothed_equity
from trading.cfd.state import (
    clear_pending_entry,
    exclude_instrument,
    get_daily_risk_tracking,
    get_equity_tracking,
    get_pending_entries,
    list_open_trades,
    load_state,
    pop_open_trade,
    record_open_trade,
    set_broker_baseline,
    set_daily_risk_tracking,
    set_equity_tracking,
    set_pending_entry,
    set_operating_mode,
)
from trading.cfd.strategy_registry import LifecycleState, get, list_by_state
from trading.cfd.trade_log import TradeRecord, load_trades
from trading.cfd.virtual_accounts import account_for_strategy, commit_trade_settlement, ensure_virtual_accounts, flush_trade_settlements
from trading.config import settings
from trading.logging_utils import get_logger
from trading.strategy.base import Action

logger = get_logger(__name__)

GRANULARITY_SECONDS = 3600  # 1 hour -- see EmaCrossoverStrategy's docstring for why H1, not M15
CANDLE_COUNT = 200  # comfortably more than slow_span=34 + atr_window=14 warmup,
# and more than regime.py's default volatility_lookback=100 + atr_window=14


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def close_overdue_demo_probes(broker, account_type, current=None):
    """Bound legacy experimental positions without applying an H1 signal exit.

    Persist intent before sell; ordinary verified settlement reconciliation owns
    accounting. Unknown/manual positions and quota deadlines are excluded.
    """
    if account_type != "demo":
        return
    current = current or datetime.now(timezone.utc)
    limits = {"TICK": 1800, "M1": 1800, "M5": 1800, "M15": 3600, "H1": 14400}
    actual = None
    for cid, meta in list_open_trades().items():
        if not meta.get("experimental") or not meta.get("broker_managed_only") or "quota_window" in meta:
            continue
        entered = datetime.fromisoformat(meta["entry_time"])
        if entered.tzinfo is None:
            raise ValueError("Probe entry timestamp must include timezone")
        if (current-entered).total_seconds() < limits.get(meta.get("entry_timeframe"), 21600):
            continue
        if actual is None:
            actual = await broker.open_contract_ids()
        if int(cid) not in actual:
            continue
        meta["exit_requested_reason"] = "legacy_demo_probe_max_holding_time"
        record_open_trade(int(cid), meta)
        await broker.close_position(int(cid))
        if int(cid) in await broker.open_contract_ids():
            raise RuntimeError("Overdue demo probe close not confirmed")


def _reserved_stake_for_open_ids(tracked_open: dict, open_ids: set[int]) -> float:
    """Cash paid as stake for bot contracts that are still open.

    Deriv deducts buy_price/stake from cash balance at entry. Adding only
    the still-open bot stakes back produces a realized-equity ledger:
    opening a position does not masquerade as a loss, while closing it
    removes the reserve and lets only realized P&L change virtual equity.
    """
    total = 0.0
    for contract_id, meta in tracked_open.items():
        try:
            cid = int(contract_id)
        except (TypeError, ValueError):
            continue
        if cid in open_ids:
            total += float(meta.get("stake", 0.0) or 0.0)
    return round(total, 10)


def _reconcile_closed_trades(tracked_open: dict, currently_open_ids: set[int], equity_now: float,
                             contract_profits: Optional[dict[int, float]] = None) -> list[TradeRecord]:
    """Attribute closed trades only from verified contract settlements.

    A balance delta can contain other trades and cash movements, even if
    only one locally tracked contract disappeared. Missing evidence stays
    unknown; the runtime fetches all settlements before applying changes.
    """
    disappeared = {cid: meta for cid, meta in tracked_open.items() if int(cid) not in currently_open_ids}
    if not disappeared:
        return []

    records = []
    for contract_id, meta in disappeared.items():
        pnl = (contract_profits or {}).get(int(contract_id))
        equity_before = meta.get("equity_before")
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
                exit_reason=meta.get("exit_requested_reason", "closed_externally (stop-loss/take-profit or manual close)"),
                regime=meta.get("regime"),
                thesis_key=meta.get("thesis_key"),
                leg=meta.get("leg"),
                virtual_account_id=meta.get("virtual_account_id"),
                horizon=meta.get("horizon"),
                entry_timeframe=meta.get("entry_timeframe"),
                context_timeframes=meta.get("context_timeframes"),
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


def _owned_by(meta: dict, owner_account_id: str) -> bool:
    """True if a tracked_open leg's metadata belongs to owner_account_id
    (or predates the virtual-account laboratory, meta.get("virtual_account_id")
    is None -- treated as this scheduler's own, same as always). False for
    any OTHER isolated $100 account's position (a timeframe champion,
    trading.cfd.timeframe_champion; a GPT research/quota account,
    trading.cfd.virtual_accounts) sharing the same Deriv demo account and
    the same tracked_open dict.

    Without this filter, a champion's own open position on an instrument
    run_once() also trades would be invisible in tracked_open's DIRECT
    sense but NOT invisible to positions_by_instrument (built straight
    from the broker's raw open_positions_list()) -- _resolve_exit_strategy_
    entry() would then fail to resolve its unrecognized strategy tag,
    fall back to "the sole ACTIVE strategy" (ema_crossover@v1, currently),
    and this scheduler would wrongly evaluate ema_crossover's exit signal
    against a position it never opened and doesn't own -- silently
    mismanaging another account's trade and double-counting it into this
    account's own Portfolio Risk Governor snapshot and occupied-slot
    count. Each isolated account must stay invisible to every other
    account's exit/entry/risk accounting, the same way two different
    human traders sharing one broker login would be."""
    return meta.get("virtual_account_id") in (None, owner_account_id)


def _legs_by_strategy(legs: list[dict], tracked_open: dict) -> dict[str, list[dict]]:
    """Splits one instrument's open legs into groups sharing the same
    strategy tag ("name@version") -- Revision 3 gap #3 (docs/
    ARCHITECTURE_AUDIT.md): an instrument can now hold independent
    positions from more than one ACTIVE strategy at once (each its own
    thesis), not just the "scalp"/"runner" legs of a single entry, so
    exit management and new-entry eligibility both need to operate per
    strategy-group, not per instrument as a whole. A leg with no tracked
    metadata (predates per-trade strategy tagging) groups under "" --
    _resolve_exit_strategy_entry's own fallback (sole ACTIVE strategy)
    still applies to that group unchanged."""
    groups: dict[str, list[dict]] = {}
    for leg in legs:
        meta = tracked_open.get(str(leg["contract_id"]))
        tag = (meta or {}).get("strategy") or ""
        groups.setdefault(tag, []).append(leg)
    return groups


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


async def run_once(bridge_command_id: Optional[str] = None) -> list[dict]:
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
    mode may cross. max_open_positions counts distinct (instrument,
    strategy) position slots, not raw contracts -- a partial-close split
    (see below) never silently doubles this count, and (per Revision 3
    gap #3, further down) two different strategies independently
    positioned on the same instrument count as two slots, not one.

    Which strategy opens a NEW position is decided per instrument, per
    run, by the Strategy Selector (trading.cfd.selector.select_for_entry)
    matching the instrument's current regime (trading.cfd.regime) against
    the Strategy Registry's ACTIVE entries -- not a single hardcoded or
    globally-fixed strategy. No ACTIVE strategy suited to the current
    regime is an explicit NO TRADE, not a guess. Each already-open
    position is always managed by the exact strategy version that opened
    it (see _resolve_exit_strategy_entry), regardless of what's ACTIVE
    now.

    More than one ACTIVE strategy can be suited to the same regime --
    trading.cfd.portfolio_allocator.compute_allocations() weights each by
    recent performance once per run, the Selector picks among matches by
    that weight, and the winning entry's stake is itself sized by its
    weight relative to the others (capped so no strategy's risk ever
    exceeds what risk_per_trade alone would already allow -- allocation
    only ever redistributes the existing budget, never raises it). This
    is docs/VISION.md's revised "Portfolio / Allocation Decision" stage,
    not a single-winner selector.

    An instrument is no longer capped at one open position at a time
    either (Revision 3 gap #3, docs/ARCHITECTURE_AUDIT.md):
    _legs_by_strategy splits an instrument's open legs into groups by
    which strategy opened them, each group is managed to its own exit
    independently, and a NEW entry is still considered afterward as long
    as at least one ACTIVE strategy suited to the current regime does
    NOT already have a position open here (select_for_entry's
    exclude_tags) -- still only one new entry decision per instrument
    per run. Two different strategies holding independent positions on
    the same instrument is two theses, not one; trading.cfd.portfolio_risk's
    ceilings are keyed on instrument+side, never on strategy, so they
    already aggregate this correctly with no change needed there. What's
    still forbidden, and still enforced (select_for_entry's exclude_tags
    always includes every strategy already positioned here): the SAME
    strategy opening a second position on an instrument it's already in
    -- that would be exactly the disguised-risk-split docs/VISION.md
    forbids, not a second opportunity. max_open_positions now counts
    distinct (instrument, strategy) position slots across the whole
    portfolio, not distinct instruments -- the closest available
    approximation of "how many genuinely independent opportunities" the
    system is holding at once.

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

    Every new entry's risk is further scaled (never raised) by
    trading.cfd.drawdown_monitor and trading.cfd.smoothed_equity: a
    drawdown from the persisted virtual-equity high-water-mark moves
    risk down a tier automatically (moderate/deep/severe, severe halting
    new entries entirely) with no human approval needed -- the same
    autonomous-risk-reduction authority trading.cfd.decay_supervisor
    already has; and a smoothed (gain-damped, loss-immediate) equity
    figure keeps a quick win from instantly scaling the next trade's
    risk up by the same proportion. Neither ever forces an exit on an
    already-open position -- only new entries are affected.

    bridge_command_id (only set by the CFD AI Demo Bridge workflow -- see
    .github/workflows/cfd-ai-demo-bridge.yml) doesn't change any decision
    made here; it's threaded through purely so the bridge's audit trail can
    correlate one comment-triggered command_id with the resulting per-
    instrument outcomes, which are always accumulated into the returned
    list regardless of whether bridge_command_id is set (the normal hourly
    schedule just discards the return value, same as before this existed).
    """
    summary: list[dict] = []

    def _record(
        instrument: str,
        outcome: str,
        reason: str,
        regime: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> None:
        summary.append({"instrument": instrument, "outcome": outcome, "reason": reason})
        record_decision(
            instrument,
            outcome,
            reason,
            regime=regime,
            strategy=strategy,
            run_id=os.environ.get("GITHUB_RUN_ID"),
            bridge_command_id=bridge_command_id,
        )

    state = load_state()
    if state.get("paused"):
        logger.info("CFD bot is paused (state/cfd_bot_state.json) -- skipping this run.")
        return summary

    if bridge_command_id:
        logger.info("Bridge-triggered run (command_id=%s)", bridge_command_id)

    # Retry any trade_settlements outbox entry from a prior run whose
    # equity/dedup write succeeded but whose separate Trade Database
    # append then failed (see commit_trade_settlement's docstring) --
    # never re-touches equity, only replays the missing log line. Same
    # first-thing-in-the-run placement as quota.py's own flush_settlements.
    flush_trade_settlements()

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
        await close_overdue_demo_probes(broker, account_type)
        broker_balance = await broker.account_equity()
        # Deriv deducts the contract stake from CASH at buy time. Cash alone
        # therefore falls when a position opens even though no loss has been
        # realized. Reconstruct realized account equity by adding back the
        # cost basis of bot-owned contracts that are actually still open.
        tracked_for_equity = list_open_trades()
        currently_open_ids = await broker.open_contract_ids()
        reserved_stake = _reserved_stake_for_open_ids(tracked_for_equity, currently_open_ids)
        broker_equity = broker_balance + reserved_stake

        broker_baseline = state.get("broker_baseline")
        if account_type == "demo" and broker_baseline is None:
            set_broker_baseline(broker_equity)
            broker_baseline = broker_equity
            logger.info(
                "First run: broker baseline recorded at %.2f (raw demo balance) -- "
                "virtual equity now tracks P&L from here, rebased onto %.2f, not the raw balance.",
                broker_balance, settings.cfd_virtual_starting_capital,
            )

        equity = equity_for_account(broker_equity, account_type, broker_baseline, settings.cfd_virtual_starting_capital)

        # Virtual sub-account lab: seed logical $100 ledgers and collect
        # genuine forward observations on M15/M5/M1. SHADOW accounts never
        # submit orders; this cannot increase broker risk.
        virtual_accounts = ensure_virtual_accounts()
        lab_rows = await collect_lab_observations(
            broker, settings.cfd_instruments, run_id=os.environ.get("GITHUB_RUN_ID")
        )
        logger.info("Virtual-account lab collected %d forward observation row(s).", len(lab_rows))

        # Smoothed Equity / High-Water-Mark + Automatic Drawdown-Tiered
        # Risk Reduction (docs/VISION.md's Revision 3 "Drawdown
        # handling"): computed from RAW equity right here, before any
        # protective check below reads it, so both react to this run's
        # real numbers, never a stale value from an earlier run.
        equity_tracking = get_equity_tracking()
        smoothed_equity = update_smoothed_equity(
            equity_tracking.get("smoothed_equity"), equity, settings.cfd_equity_smoothing_alpha,
        )
        high_water_mark = update_high_water_mark(equity_tracking.get("high_water_mark"), equity)
        set_equity_tracking(smoothed_equity, high_water_mark)

        drawdown_thresholds = DrawdownThresholds(
            moderate_pct=settings.cfd_drawdown_moderate_pct,
            deep_pct=settings.cfd_drawdown_deep_pct,
            severe_pct=settings.cfd_drawdown_severe_pct,
            moderate_multiplier=settings.cfd_drawdown_moderate_multiplier,
            deep_multiplier=settings.cfd_drawdown_deep_multiplier,
        )
        drawdown_tier = classify_drawdown_tier(equity, high_water_mark, drawdown_thresholds)
        drawdown_multiplier = drawdown_risk_multiplier(drawdown_tier, drawdown_thresholds)

        # Autonomy boundary: the manager may reduce risk on its own but may
        # never raise it. Persist a defensive/recovery mode when drawdown
        # warrants it; normal conditions never auto-upgrade the current mode.
        current_mode = state.get("operating_mode", NORMAL)
        auto_mode, auto_reason = choose_autonomous_mode(drawdown_tier, current_mode)
        if auto_mode != current_mode:
            set_operating_mode(auto_mode, auto_reason)
            state["operating_mode"] = auto_mode
            state["operating_mode_reason"] = auto_reason
            logger.warning("Autonomous risk reduction: operating mode %s -> %s (%s)", current_mode, auto_mode, auto_reason)

        if drawdown_tier != DRAWDOWN_NORMAL:
            logger.warning(
                "Drawdown tier=%s (equity %.2f vs high-water-mark %.2f) -- new-entry risk scaled by %.2fx this run.",
                drawdown_tier, equity, high_water_mark, drawdown_multiplier,
            )
        # Sizing-only scale factor: combines the drawdown multiplier with
        # how far the smoothed (gain-damped) equity figure currently
        # trails raw equity -- both only ever shrink new-entry risk,
        # never raise it above what risk_per_trade alone would already
        # allow (enforced again, at the lowest level, in risk.py's
        # stake_and_limits()).
        sizing_scale_factor = drawdown_multiplier * (smoothed_equity / equity if equity > 0 else 1.0)

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
        # Reuse the broker-open set captured for equity reconstruction so
        # reconciliation and the equity snapshot describe the same instant.
        reconciled_ids: set[int] = set()
        contract_profits = {}
        for cid in tracked_open:
            if int(cid) not in currently_open_ids:
                contract_profits[int(cid)] = await broker.settled_profit(int(cid))
        for record in _reconcile_closed_trades(tracked_open, currently_open_ids, equity, contract_profits):
            meta = tracked_open[str(record.contract_id)]
            if "quota_window" in meta:
                commit_quota_close(record, meta["quota_window"])
                reconciled_ids.add(record.contract_id)
                continue
            # One atomic settlement (equity mutation, Trade Database queue,
            # and open_trades removal together, keyed by contract_id) --
            # not three separate calls. Those three used to be able to
            # apply this contract's P&L twice: if record_virtual_close
            # succeeded but record_trade then raised, the contract stayed
            # in open_trades un-popped, so the next run's retry walked
            # through record_virtual_close again for the same pnl.
            commit_trade_settlement(record)
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
            if not _owned_by(tracked_open.get(str(p["contract_id"]), {}), "core_h1"):
                continue  # another isolated $100 account's position -- see _owned_by's docstring
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
            pending = pending_entries[pending_instrument]
            if pending.get("quota_intent"):
                # An absent position may already have closed at the broker.
                # Do not erase an ambiguous quota buy without attribution.
                if not any(m.get("instrument") == pending_instrument for _, m in adoptions):
                    exclude_instrument(pending_instrument, "unresolved quota buy intent")
                    continue
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
            if int(cid) not in reconciled_ids and _owned_by(meta, "core_h1")
        ]
        risk_ceilings = PortfolioRiskCeilings(
            max_thesis_risk_pct=settings.cfd_max_thesis_risk_pct,
            max_correlated_risk_pct=settings.cfd_max_correlated_risk_pct,
            max_portfolio_risk_pct=settings.cfd_max_portfolio_risk_pct,
            max_exposure_multiple=settings.cfd_max_exposure_multiple,
        )

        # Revision 3 gap #3 (docs/ARCHITECTURE_AUDIT.md): counts distinct
        # (instrument, strategy) position slots, not distinct instruments
        # -- mutated in place below as groups close or a new entry opens
        # within this run's own loop, same pattern open_risk_positions
        # already uses, so later instruments always see the up-to-date
        # total.
        total_open_slots = sum(
            len(_legs_by_strategy(legs, tracked_open)) for legs in positions_by_instrument.values()
        )

        for instrument in settings.cfd_instruments:
            if instrument in excluded:
                logger.debug("%s: excluded (%s)", instrument, excluded[instrument] or "no reason given")
                _record(instrument, "NO_TRADE", f"excluded: {excluded[instrument] or 'no reason given'}")
                continue

            bars = await broker.get_candles(instrument, granularity_seconds=GRANULARITY_SECONDS, count=CANDLE_COUNT)
            if len(bars) < 2:
                logger.debug("%s: not enough candles yet", instrument)
                record_incident(
                    "data_quality",
                    severity="warning",
                    message="insufficient candle history",
                    instrument=instrument,
                    correlation_id=os.environ.get("GITHUB_RUN_ID"),
                    metadata={"bar_count": len(bars)},
                )
                _record(instrument, "NO_TRADE", "insufficient candle history")
                continue

            regime = classify_regime(
                bars,
                settings.cfd_regime_adx_window,
                settings.cfd_regime_trend_threshold,
                atr_window=settings.cfd_regime_atr_window,
                volatility_lookback=settings.cfd_regime_volatility_lookback,
                unstable_volatility_ratio=settings.cfd_regime_unstable_volatility_ratio,
            )

            # Event context is SHADOW-ONLY until blackout validation clears
            # the project's TRAIN/TEST + forward qualification discipline.
            # We tag event windows now so later analysis has point-in-time
            # evidence; this does not alter BUY/SELL/NO TRADE yet.
            matched_event = in_blackout_window(datetime.now(timezone.utc), OFFICIAL_EVENTS)
            if matched_event is not None:
                record_incident(
                    "event_blackout",
                    severity="info",
                    message=f"shadow event window: {matched_event.name}",
                    instrument=instrument,
                    correlation_id=os.environ.get("GITHUB_RUN_ID"),
                    metadata={"regime": regime, "mode": "shadow_only"},
                )

            # Paper Trading runs independently of the real position below
            # -- every PAPER-state strategy gets evaluated on this same
            # instrument/candles/regime regardless of what's happening
            # with real (or virtual-real) capital.
            run_paper_trading(instrument, bars, regime)

            legs = positions_by_instrument.get(instrument, [])
            strategy_groups = _legs_by_strategy(legs, tracked_open)
            occupied_tags: set[str] = set()

            for strategy_tag, group_legs in strategy_groups.items():
                first_meta = tracked_open.get(str(group_legs[0]["contract_id"]))
                # Short-horizon/manual demo probes can be explicitly marked
                # broker_managed_only. Their timeframe-specific entry logic is
                # not represented by an ACTIVE H1 strategy, so applying the
                # H1 strategy's signal-exit here would mix incompatible
                # timeframes. Deriv's own stop-loss/take-profit remains live;
                # reconciliation records the realized result on a later run.
                if first_meta and first_meta.get("broker_managed_only"):
                    occupied_tags.add(strategy_tag)
                    continue
                exit_entry = _resolve_exit_strategy_entry(first_meta)
                if exit_entry is None:
                    logger.warning(
                        "%s: can't determine which strategy opened this position (no tracked metadata, and not "
                        "exactly one ACTIVE strategy to fall back to) -- leaving it to Deriv's own stop-loss/"
                        "take-profit and reconciliation next run.",
                        instrument,
                    )
                    occupied_tags.add(strategy_tag)  # still open, still occupies its slot -- just unmanaged
                    continue

                in_position = group_legs[0]["side"]
                exit_strategy = exit_entry.build()
                prepared = exit_strategy.prepare(bars)
                row, prev_row = prepared.iloc[-1], prepared.iloc[-2]
                signal = exit_strategy.signal_for_row(instrument, row, prev_row, in_position)
                is_exit_signal = (in_position == "long" and signal.action == Action.SELL) or (
                    in_position == "short" and signal.action == Action.BUY
                )
                current_atr = row.get("atr") if hasattr(row, "get") else None
                current_atr = 0.0 if current_atr is None or pd.isna(current_atr) else float(current_atr)

                group_still_open = False
                for leg in group_legs:
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
                        group_still_open = True
                        continue

                    logger.info(
                        "%s: closing %s leg (contract %d, %s position) -- %s",
                        instrument, leg_tag or "untagged", contract_id, in_position, close_reason,
                    )
                    equity_before = risk.equity
                    await broker.close_position(contract_id)
                    new_balance = await broker.account_equity()
                    remaining_ids = await broker.open_contract_ids()
                    if contract_id in remaining_ids:
                        raise RuntimeError("Close not confirmed; retaining tracked contract for reconciliation")
                    remaining_tracked = list_open_trades()
                    remaining_reserved = _reserved_stake_for_open_ids(remaining_tracked, remaining_ids)
                    new_equity = equity_for_account(
                        new_balance + remaining_reserved,
                        account_type,
                        broker_baseline,
                        settings.cfd_virtual_starting_capital,
                    )
                    pnl = await broker.settled_profit(contract_id)
                    risk.register_close(pnl)
                    equity = new_equity
                    if meta:
                        # One atomic settlement (equity mutation, Trade
                        # Database queue, and open_trades removal together,
                        # keyed by contract_id) instead of three separate
                        # calls -- see commit_trade_settlement's docstring
                        # for the double-counting bug this replaces (a
                        # confirmed $4.50 win applied twice took a $100
                        # account to $109 when record_virtual_close
                        # succeeded but record_trade then raised, leaving
                        # this contract un-popped for a next-run retry).
                        commit_trade_settlement(
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
                                virtual_account_id=meta.get("virtual_account_id"),
                                horizon=meta.get("horizon"),
                                entry_timeframe=meta.get("entry_timeframe"),
                                context_timeframes=meta.get("context_timeframes"),
                            )
                        )
                    else:
                        logger.warning(
                            "%s: closed contract %d with no tracked entry metadata "
                            "(opened before trade logging existed) -- pnl not logged to the trade database.",
                            instrument, contract_id,
                        )
                        # No tracked metadata means commit_trade_settlement
                        # (which needs meta to build a TradeRecord) never
                        # ran to pop this -- do it directly so a
                        # metadata-less contract doesn't stay tracked open
                        # forever.
                        pop_open_trade(contract_id)
                    open_risk_positions = [p for p in open_risk_positions if p.contract_id != contract_id]

                if group_still_open:
                    occupied_tags.add(strategy_tag)
                else:
                    total_open_slots -= 1  # this strategy's whole position on this instrument just closed

            # Consider a NEW entry regardless of whether one or more other
            # strategies already hold their own independent position(s)
            # here (Revision 3 gap #3) -- select_for_entry excludes every
            # tag in occupied_tags, so this can only ever add a genuinely
            # different strategy's thesis, never double up the same one.
            entry_candidate = select_for_entry(regime, allocations, exclude_tags=occupied_tags)
            if entry_candidate is None:
                logger.debug(
                    "%s: NO TRADE (regime=%s, no ACTIVE strategy suited to it with an available slot)",
                    instrument, regime,
                )
                _record(instrument, "NO_TRADE", f"regime={regime}, no ACTIVE strategy suited to it with an available slot", regime=regime)
                continue

            strategy = entry_candidate.build()
            prepared = strategy.prepare(bars)
            row, prev_row = prepared.iloc[-1], prepared.iloc[-2]
            signal = strategy.signal_for_row(instrument, row, prev_row, None)

            if signal.action == Action.HOLD:
                logger.debug("%s: %s", instrument, signal.reason)
                _record(instrument, "NO_TRADE", signal.reason, regime=regime, strategy=f"{entry_candidate.name}@{entry_candidate.version}")
                continue
            if total_open_slots >= effective_max_positions:
                logger.info("Skipping %s: max open positions reached", instrument)
                _record(instrument, "NO_TRADE", "max open positions reached")
                continue

            strategy_tag = f"{entry_candidate.name}@{entry_candidate.version}"
            weight = allocations.get(strategy_tag, 1.0 / n_active if n_active else 1.0)
            risk_per_trade_override = effective_risk * risk_scale_factor(weight, n_active) * sizing_scale_factor

            stake, stop_loss_amount, take_profit_amount = risk.stake_and_limits(
                signal.price, signal.stop_price, signal.take_profit_price,
                risk_per_trade_override=risk_per_trade_override,
            )
            if stake <= 0:
                logger.info("Skipping %s: stake computed as 0 (risk limit, halt, or below Deriv's minimum stake)", instrument)
                _record(instrument, "NO_TRADE", "stake computed as 0 (risk limit, halt, or below Deriv's minimum stake)")
                continue

            side = "long" if signal.action == Action.BUY else "short"
            new_notional = stake * risk.multiplier
            rejection = check_new_position(
                open_risk_positions, instrument, side, stop_loss_amount, new_notional, risk.equity, risk_ceilings,
            )
            if rejection is not None:
                logger.info("Skipping %s: Portfolio Risk Governor rejected this entry -- %s", instrument, rejection)
                record_incident(
                    "risk_control",
                    severity="info",
                    message=rejection,
                    instrument=instrument,
                    correlation_id=os.environ.get("GITHUB_RUN_ID"),
                    metadata={"regime": regime, "strategy": strategy_tag},
                )
                _record(instrument, "REJECTED", rejection, regime=regime, strategy=strategy_tag)
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
            virtual_account_id = account_for_strategy(strategy_tag) or "core_h1"
            virtual_account = virtual_accounts.get(virtual_account_id, {})
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
                    "virtual_account_id": virtual_account_id,
                    "horizon": virtual_account.get("horizon", "core"),
                    "entry_timeframe": virtual_account.get("entry_timeframe", "H1"),
                    "context_timeframes": virtual_account.get("context_timeframes", ["H4", "H1"]),
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
                total_open_slots += 1
                _record(instrument, "TRADE", f"{side} {strategy_tag} ({len(opened_legs)} leg(s))", regime=regime, strategy=strategy_tag)
            else:
                record_incident(
                    "broker_error",
                    severity="error",
                    message="order submitted but no contract_id returned for any leg",
                    instrument=instrument,
                    correlation_id=os.environ.get("GITHUB_RUN_ID"),
                    metadata={"regime": regime, "strategy": strategy_tag},
                )
                _record(instrument, "ERROR", "order submitted but no contract_id returned for any leg", regime=regime, strategy=strategy_tag)

        set_daily_risk_tracking(today, risk.daily_start_equity, risk.halted)
        return summary
    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(run_once())

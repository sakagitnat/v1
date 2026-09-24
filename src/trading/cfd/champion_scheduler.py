"""Evaluates the three timeframe-champion accounts without a dedicated
real-time loop of their own (H1's champion, core_h1, is already wired
into scheduler.run_once()). See trading.cfd.timeframe_champion for what
a "champion" is and why its assignment is kept separate from the H1
production Strategy Registry.

Must always run in the same process as run_once(), never as a
separately scheduled workflow -- both read/write the same shared
state/cfd_bot_state.json (open_trades in particular), and GitHub
Actions has no way to serialize two independently-scheduled workflows
short of a concurrency group covering both, which would just make them
queue behind each other rather than genuinely run together. One
process, one await chain, is what actually guarantees neither this nor
run_once() ever executes concurrently with the other.

Each of the three champions trades its own isolated $100 virtual
account -- own equity, own daily-loss breaker, own position -- never a
shared pool, and never visible to run_once()'s own accounting (see
scheduler._owned_by()). Exit is price-bound (Deriv's own stop_loss/
take_profit, submitted with the order and enforced server-side, same
mechanism core_h1 relies on) or the assigned strategy's own signal exit
-- never a timeframe-duration-based forced close.

An unassigned champion (trading.cfd.timeframe_champion.get_assignment()
returns None) is a standing NO TRADE for every instrument at that
timeframe -- expected until something clears TRAIN/TEST/walk-forward at
that granularity, not an error.

Safety gates, matching run_once()'s own (2026-09-24 review fix -- v1 of
this module had neither): a paused bot state is a full stop, same as
run_once() itself; an excluded instrument blocks new entries the same
way it does there. Both are read fresh from state each run rather than
trusted from a caller, so any caller of run_champions()/
_run_one_champion() gets these for free, not just run_normal().

Crash-recovery reconciliation (2026-09-24 review fix): a pending-entry
marker is recorded before every order submission and cleared after, the
same intent-then-commit pattern run_once() uses -- but in its own
champion_pending_entries state namespace (trading.cfd.state), never
"pending_entries", because that one is unconditionally swept clean by
run_once() at the end of every single run (see
state.get_champion_pending_entries' docstring for why sharing it would
silently defeat this).
"""
from __future__ import annotations

from datetime import datetime, timezone

from trading.cfd.broker import DerivBroker
from trading.cfd.regime import classify_regime
from trading.cfd.risk import CfdRiskManager
from trading.cfd.state import (
    clear_champion_pending_entry,
    get_champion_daily_risk_tracking,
    get_champion_pending_entries,
    list_open_trades,
    load_state,
    pop_open_trade,
    record_open_trade,
    set_champion_daily_risk_tracking,
    set_champion_pending_entry,
)
from trading.cfd.strategy_registry import STRATEGY_CLASSES
from trading.cfd.timeframe_champion import CHAMPION_SPECS, MANAGED_CHAMPIONS, get_assignment
from trading.cfd.trade_log import TradeRecord, record_trade
from trading.cfd.virtual_accounts import ensure_virtual_accounts, record_virtual_close
from trading.config import settings
from trading.logging_utils import get_logger
from trading.strategy.base import Action

logger = get_logger(__name__)

CANDLE_COUNT = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_strategy(strategy_name: str, params: dict):
    cls = STRATEGY_CLASSES.get(strategy_name)
    if cls is None:
        return None
    return cls(**(params or {}))


async def run_champions(broker: DerivBroker) -> list[dict]:
    summary: list[dict] = []
    for account_id in MANAGED_CHAMPIONS:
        summary.extend(await _run_one_champion(broker, account_id))
    return summary


async def _run_one_champion(broker: DerivBroker, account_id: str) -> list[dict]:
    granularity_seconds, context_timeframes = CHAMPION_SPECS[account_id]

    state = load_state()
    if state.get("paused"):
        return [{"instrument": "*", "outcome": "NO_TRADE", "reason": f"{account_id}: bot paused"}]
    excluded = dict(state.get("excluded_instruments") or {})

    summary: list[dict] = []

    accounts = ensure_virtual_accounts()
    account = accounts.get(account_id, {})
    equity = float(account.get("equity", 100.0))

    today = datetime.now(timezone.utc).date().isoformat()
    daily = get_champion_daily_risk_tracking(account_id)
    if daily.get("date") == today:
        daily_start_equity = daily.get("start_equity")
        initially_halted = daily.get("halted", False)
    else:
        daily_start_equity = equity
        initially_halted = False

    risk = CfdRiskManager(
        equity=equity,
        risk_per_trade=settings.cfd_risk_per_trade,
        max_open_positions=len(settings.cfd_instruments),
        max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
        min_stake=settings.cfd_min_stake,
        daily_start_equity=daily_start_equity,
        initially_halted=initially_halted,
        stake_safety_margin=settings.cfd_stake_safety_margin,
    )

    tracked_open = list_open_trades()
    own_open_by_instrument = {
        meta["instrument"]: (int(cid), meta)
        for cid, meta in tracked_open.items()
        if meta.get("virtual_account_id") == account_id
    }
    all_tracked_contract_ids = {int(cid) for cid in tracked_open}

    open_positions = await broker.open_positions_list()
    currently_open_ids = {p["contract_id"] for p in open_positions}
    open_ids_by_instrument: dict[str, list[int]] = {}
    for p in open_positions:
        open_ids_by_instrument.setdefault(p["instrument"], []).append(p["contract_id"])

    pending_entries = get_champion_pending_entries()
    assignment = get_assignment(account_id)
    current_strategy = _build_strategy(assignment.strategy_name, assignment.params) if assignment is not None else None

    for instrument in settings.cfd_instruments:
        pending_key = f"{account_id}:{instrument}"
        pending = pending_entries.get(pending_key)
        if pending is not None and instrument not in own_open_by_instrument:
            # A run that submitted this order but crashed before its
            # record_open_trade commit ever landed -- one-shot recovery
            # window, same as run_once()'s own pending entries: adopt if
            # exactly one untracked (by ANY account) contract shows up on
            # this instrument, otherwise the marker can't be resolved and
            # is dropped rather than chased forever.
            candidates = [cid for cid in open_ids_by_instrument.get(instrument, []) if cid not in all_tracked_contract_ids]
            if len(candidates) == 1:
                contract_id = candidates[0]
                record_open_trade(contract_id, pending)
                own_open_by_instrument[instrument] = (contract_id, pending)
                all_tracked_contract_ids.add(contract_id)
                logger.warning(
                    "%s: %s recovered attribution for contract %d from a pending entry interrupted last run.",
                    account_id, instrument, contract_id,
                )
            else:
                logger.warning(
                    "%s: %s pending entry could not be resolved (%d candidate contract(s)) -- dropping marker.",
                    account_id, instrument, len(candidates),
                )
            clear_champion_pending_entry(pending_key)

        owned = own_open_by_instrument.get(instrument)

        if owned is not None:
            contract_id, meta = owned
            bars = await broker.get_candles(instrument, granularity_seconds=granularity_seconds, count=CANDLE_COUNT)
            exit_strategy = _build_strategy(meta.get("strategy", ""), meta.get("strategy_params") or {})
            signal_exit = False
            if exit_strategy is not None and len(bars) >= 2:
                prepared = exit_strategy.prepare(bars)
                row, prev_row = prepared.iloc[-1], prepared.iloc[-2]
                exit_signal = exit_strategy.signal_for_row(instrument, row, prev_row, meta.get("side"))
                signal_exit = (meta.get("side") == "long" and exit_signal.action == Action.SELL) or (
                    meta.get("side") == "short" and exit_signal.action == Action.BUY
                )

            if signal_exit:
                await broker.close_position(contract_id)
            elif contract_id in currently_open_ids:
                summary.append({"instrument": instrument, "outcome": "NO_TRADE", "reason": f"{account_id}: position still open"})
                continue
            # else: contract already gone from Deriv's side -- its own
            # stop_loss/take_profit fired. Either way, read the exact
            # contract-level P&L rather than inferring it from a balance
            # delta (several champions' contracts can settle in one run).
            try:
                pnl = await broker.settled_profit(contract_id)
            except RuntimeError as exc:
                summary.append({"instrument": instrument, "outcome": "ERROR", "reason": f"{account_id}: settlement not yet confirmed ({exc})"})
                continue

            # Persist the durable records (virtual ledger, Trade Database)
            # BEFORE removing this contract's open_trades tracking entry.
            # pop_open_trade is the last step, not the first: if
            # record_virtual_close/record_trade below ever raises, this
            # contract stays tracked as open for the next run to retry,
            # instead of silently losing the only local record that ties
            # this settled contract back to an account/strategy/thesis.
            record_virtual_close(account_id, pnl)
            equity_before = meta.get("equity_before")
            record_trade(
                TradeRecord(
                    contract_id=contract_id,
                    instrument=instrument,
                    strategy=meta.get("strategy", ""),
                    side=meta.get("side", ""),
                    entry_time=meta.get("entry_time", ""),
                    exit_time=_now_iso(),
                    entry_price=meta.get("entry_price", 0.0),
                    stake=meta.get("stake", 0.0),
                    risk_amount=meta.get("risk_amount", 0.0),
                    pnl=pnl,
                    equity_before=equity_before,
                    equity_after=round(float(equity_before) + pnl, 2) if equity_before is not None else None,
                    exit_reason="signal_exit" if signal_exit else "stop_loss_or_take_profit (Deriv-managed)",
                    regime=meta.get("regime"),
                    thesis_key=meta.get("thesis_key"),
                    virtual_account_id=account_id,
                    horizon=meta.get("horizon"),
                    entry_timeframe=meta.get("entry_timeframe"),
                    context_timeframes=meta.get("context_timeframes"),
                )
            )
            pop_open_trade(contract_id)
            risk.register_close(pnl)
            summary.append({"instrument": instrument, "outcome": "TRADE", "reason": f"{account_id}: closed, pnl={pnl:+.2f}"})
            continue

        if instrument in excluded:
            summary.append({"instrument": instrument, "outcome": "NO_TRADE", "reason": f"{account_id}: excluded ({excluded[instrument] or 'no reason given'})"})
            continue

        if current_strategy is None:
            summary.append({"instrument": instrument, "outcome": "NO_TRADE", "reason": f"{account_id}: unassigned (no validated strategy for this timeframe yet)"})
            continue

        bars = await broker.get_candles(instrument, granularity_seconds=granularity_seconds, count=CANDLE_COUNT)
        if len(bars) < 2:
            summary.append({"instrument": instrument, "outcome": "NO_TRADE", "reason": f"{account_id}: insufficient candle history"})
            continue

        regime = classify_regime(
            bars,
            settings.cfd_regime_adx_window,
            settings.cfd_regime_trend_threshold,
            atr_window=settings.cfd_regime_atr_window,
            volatility_lookback=settings.cfd_regime_volatility_lookback,
            unstable_volatility_ratio=settings.cfd_regime_unstable_volatility_ratio,
        )

        prepared = current_strategy.prepare(bars)
        row, prev_row = prepared.iloc[-1], prepared.iloc[-2]
        signal = current_strategy.signal_for_row(instrument, row, prev_row, None)
        if signal.action == Action.HOLD:
            summary.append({"instrument": instrument, "outcome": "NO_TRADE", "reason": signal.reason})
            continue

        stake, stop_loss_amount, take_profit_amount = risk.stake_and_limits(signal.price, signal.stop_price, signal.take_profit_price)
        if stake <= 0:
            summary.append({"instrument": instrument, "outcome": "NO_TRADE", "reason": f"{account_id}: stake computed as 0 (risk limit, halt, or below minimum)"})
            continue

        side = "long" if signal.action == Action.BUY else "short"
        entry_meta = {
            "instrument": instrument,
            "strategy": assignment.strategy_name,
            "strategy_params": assignment.params,
            "side": side,
            "entry_time": _now_iso(),
            "entry_price": signal.price,
            "stake": stake,
            "risk_amount": stop_loss_amount,
            "multiplier": risk.multiplier,
            "thesis_key": f"{instrument}:{side}:{account_id}",
            "equity_before": risk.equity,
            "regime": regime,
            "virtual_account_id": account_id,
            "horizon": "champion",
            "entry_timeframe": account.get("entry_timeframe"),
            "context_timeframes": list(context_timeframes),
        }
        # Record intent before submitting -- if the process dies between
        # the broker accepting this order and record_open_trade below
        # ever committing, the next run's reconciliation (top of this
        # loop) can still recover attribution instead of leaving an
        # unattributed contract on the account.
        set_champion_pending_entry(pending_key, entry_meta)
        result = await broker.submit_multiplier_order(instrument, side, stake, risk.multiplier, stop_loss_amount, take_profit_amount)
        contract_id = result.get("buy", {}).get("contract_id")
        if contract_id is None:
            summary.append({"instrument": instrument, "outcome": "ERROR", "reason": f"{account_id}: order submitted but no contract_id returned"})
            # Leave the pending marker: genuinely ambiguous whether Deriv
            # actually opened a contract here, so next run's
            # reconciliation gets a chance to find and adopt it if so.
            continue

        record_open_trade(contract_id, entry_meta)
        clear_champion_pending_entry(pending_key)
        risk.register_open()
        summary.append({"instrument": instrument, "outcome": "TRADE", "reason": f"{account_id}: {side} {assignment.strategy_name} stake={stake:.2f}"})

    set_champion_daily_risk_tracking(account_id, today, risk.daily_start_equity, risk.halted)
    return summary

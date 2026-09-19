import asyncio
from datetime import datetime, timezone

from trading.cfd.broker import DerivBroker
from trading.cfd.capital import equity_for_account
from trading.cfd.risk import CfdRiskManager
from trading.cfd.state import (
    list_open_trades,
    load_state,
    pop_open_trade,
    record_open_trade,
    set_broker_baseline,
    set_capital_floor,
)
from trading.cfd.strategy_registry import get_active_strategy
from trading.cfd.trade_log import TradeRecord, record_trade
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
            )
        )
    return records


async def run_once():
    """Evaluate the EMA crossover strategy on the latest completed H1
    candle for each configured instrument and place/close orders
    accordingly. Meant to run roughly hourly during market hours via a
    scheduled GitHub Actions workflow -- see .github/workflows/
    cfd-trading.yml.

    Confirmed end-to-end against the real Deriv API (connect, buy,
    portfolio read, sell) -- see src/trading/cfd/broker.py's docstring.

    Every risk/sizing decision here uses *virtual* equity on a demo
    account, never the raw ~$10,000 Deriv demo balance -- see
    trading.cfd.capital and docs/VISION.md's "Capital model" section.

    Which strategy actually trades is resolved from the Strategy Registry
    (trading.cfd.strategy_registry) -- exactly one strategy must be marked
    ACTIVE, or this raises rather than guessing. See `cfd_cli.py
    list-strategies` / `promote-strategy`.
    """
    state = load_state()
    if state.get("paused"):
        logger.info("CFD bot is paused (state/cfd_bot_state.json) -- skipping this run.")
        return

    active_entry = get_active_strategy()  # raises if zero or >1 ACTIVE -- fail fast, before spending an API call
    strategy_tag = f"{active_entry.name}@{active_entry.version}"

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

        capital_floor = state.get("capital_floor")
        if capital_floor is None:
            # First run: protect the starting (virtual) balance by default,
            # same as the stock system's "set-floor" step -- but automatic
            # here since there's no equivalent manual first command yet.
            set_capital_floor(equity)
            capital_floor = equity
            logger.info("First run: capital floor set to starting virtual equity %.2f", equity)

        risk = CfdRiskManager(
            equity=equity,
            risk_per_trade=settings.cfd_risk_per_trade,
            max_open_positions=settings.cfd_max_open_positions,
            max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
            capital_floor=capital_floor,
            min_stake=settings.cfd_min_stake,
        )
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
        strategy = active_entry.build()

        for instrument in settings.cfd_instruments:
            if instrument in excluded:
                logger.debug("%s: excluded (%s)", instrument, excluded[instrument] or "no reason given")
                continue

            bars = await broker.get_candles(instrument, granularity_seconds=GRANULARITY_SECONDS, count=CANDLE_COUNT)
            if len(bars) < 2:
                logger.debug("%s: not enough candles yet", instrument)
                continue

            prepared = strategy.prepare(bars)
            row, prev_row = prepared.iloc[-1], prepared.iloc[-2]
            position = open_positions.get(instrument)
            in_position = position["side"] if position else None

            signal = strategy.signal_for_row(instrument, row, prev_row, in_position)

            if in_position is not None:
                is_exit = (in_position == "long" and signal.action == Action.SELL) or (
                    in_position == "short" and signal.action == Action.BUY
                )
                if is_exit:
                    logger.info("%s: closing %s position (%s)", instrument, in_position, signal.reason)
                    contract_id = position["contract_id"]
                    meta = pop_open_trade(contract_id)
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
                                strategy=meta.get("strategy", strategy_tag),
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
                            )
                        )
                    else:
                        logger.warning(
                            "%s: closed contract %d with no tracked entry metadata "
                            "(opened before trade logging existed) -- pnl not logged to the trade database.",
                            instrument, contract_id,
                        )
                continue

            if signal.action == Action.HOLD:
                logger.debug("%s: %s", instrument, signal.reason)
                continue
            if len(open_positions) >= settings.cfd_max_open_positions:
                logger.info("Skipping %s: max open positions reached", instrument)
                continue

            stake, stop_loss_amount, take_profit_amount = risk.stake_and_limits(
                signal.price, signal.stop_price, signal.take_profit_price
            )
            if stake <= 0:
                logger.info("Skipping %s: stake computed as 0 (risk limit, halt, or below Deriv's minimum stake)", instrument)
                continue

            side = "long" if signal.action == Action.BUY else "short"
            logger.info(
                "%s %s stake=%.2f (stop-loss $%.2f, take-profit $%.2f) -- %s",
                side.upper(), instrument, stake, stop_loss_amount, take_profit_amount, signal.reason,
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
                    },
                )
    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(run_once())

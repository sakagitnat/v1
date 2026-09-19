import asyncio

from trading.cfd.broker import DerivBroker
from trading.cfd.risk import CfdRiskManager
from trading.cfd.state import (
    initialize_virtual_account,
    load_state,
    set_capital_floor,
    virtual_equity_for_broker_equity,
)
from trading.cfd.strategy import EmaCrossoverStrategy
from trading.config import settings
from trading.logging_utils import get_logger
from trading.strategy.base import Action

logger = get_logger(__name__)

GRANULARITY_SECONDS = 3600
CANDLE_COUNT = 200


async def run_once():
    """Run one Deriv Multipliers evaluation pass.

    Demo accounts are deliberately sized from a virtual account that starts
    at CFD_VIRTUAL_STARTING_CAPITAL (default $100), not from Deriv's forced
    ~$10,000 demo balance. The virtual account changes dollar-for-dollar with
    demo P&L, so compounding and drawdown remain realistic for a future
    ~$100 real account without deliberately burning the demo balance down.
    """
    state = load_state()
    if state.get("paused"):
        logger.info("CFD bot is paused (state/cfd_bot_state.json) -- skipping this run.")
        return

    broker = DerivBroker()
    try:
        account = await broker.connect()
        broker_equity = await broker.account_equity()

        if account.get("account_type") == "demo":
            state = initialize_virtual_account(
                broker_equity=broker_equity,
                starting_capital=settings.cfd_virtual_starting_capital,
            )
            equity = virtual_equity_for_broker_equity(state, broker_equity)
            logger.info(
                "Demo balance %.2f mapped to virtual trading equity %.2f (start %.2f)",
                broker_equity,
                equity,
                settings.cfd_virtual_starting_capital,
            )
        else:
            equity = broker_equity

        capital_floor = state.get("capital_floor")
        if capital_floor is None:
            # Allow normal losses while enforcing an account-level hard stop.
            capital_floor = equity * (1.0 - settings.cfd_max_account_drawdown_pct)
            set_capital_floor(capital_floor)
            logger.info(
                "First run: capital floor set to %.2f (%.1f%% max account drawdown from %.2f)",
                capital_floor,
                settings.cfd_max_account_drawdown_pct * 100,
                equity,
            )

        risk = CfdRiskManager(
            equity=equity,
            risk_per_trade=settings.cfd_risk_per_trade,
            max_open_positions=settings.cfd_max_open_positions,
            max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
            capital_floor=capital_floor,
        )
        if risk.below_floor():
            logger.warning(
                "Trading equity %.2f is below hard floor %.2f -- no new entries this run.",
                equity,
                capital_floor,
            )

        excluded = state.get("excluded_instruments") or {}
        open_positions = await broker.open_positions()
        strategy = EmaCrossoverStrategy()

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
                    await broker.close_position(position["contract_id"])
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
                logger.info("Skipping %s: stake computed as 0", instrument)
                continue

            side = "long" if signal.action == Action.BUY else "short"
            logger.info(
                "%s %s stake=%.2f (virtual equity %.2f; stop-loss $%.2f, take-profit $%.2f) -- %s",
                side.upper(),
                instrument,
                stake,
                equity,
                stop_loss_amount,
                take_profit_amount,
                signal.reason,
            )
            result = await broker.submit_multiplier_order(
                instrument, side, stake, risk.multiplier, stop_loss_amount, take_profit_amount
            )
            contract_id = result.get("buy", {}).get("contract_id")
            open_positions[instrument] = {"contract_id": contract_id, "side": side}
    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(run_once())

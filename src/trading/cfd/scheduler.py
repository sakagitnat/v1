from trading.cfd.broker import OandaBroker
from trading.cfd.risk import CfdRiskManager
from trading.cfd.state import load_state, set_capital_floor
from trading.cfd.strategy import EmaCrossoverStrategy
from trading.config import settings
from trading.logging_utils import get_logger
from trading.strategy.base import Action

logger = get_logger(__name__)

GRANULARITY = "M15"
CANDLE_COUNT = 200  # comfortably more than slow_span=26 + atr_window=14 warmup


def run_once():
    """Evaluate the EMA crossover strategy on the latest completed M15
    candle for each configured instrument and place/close orders
    accordingly. Meant to run every 15-30 minutes during market hours via
    a scheduled GitHub Actions workflow -- see .github/workflows/
    cfd-trading.yml.

    UNTESTED against the real OANDA API as of writing -- see broker.py's
    docstring. Validate end-to-end against a real practice account before
    trusting it.
    """
    state = load_state()
    if state.get("paused"):
        logger.info("CFD bot is paused (state/cfd_bot_state.json) -- skipping this run.")
        return

    broker = OandaBroker()
    equity = broker.account_equity()
    capital_floor = state.get("capital_floor")
    if capital_floor is None:
        # First run: protect the starting balance by default, same as the
        # stock system's "set-floor" step -- but automatic here since
        # there's no equivalent manual first command for this system yet.
        set_capital_floor(equity)
        capital_floor = equity
        logger.info("First run: capital floor set to starting equity %.2f", equity)

    risk = CfdRiskManager(
        equity=equity,
        risk_per_trade=settings.cfd_risk_per_trade,
        max_open_positions=settings.cfd_max_open_positions,
        max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
        capital_floor=capital_floor,
    )
    if risk.below_floor():
        logger.info("Equity %.2f is below the capital floor %.2f -- no new entries this run.", equity, capital_floor)

    excluded = state.get("excluded_instruments") or {}
    open_positions = broker.open_positions()
    strategy = EmaCrossoverStrategy()

    for instrument in settings.cfd_instruments:
        if instrument in excluded:
            logger.debug("%s: excluded (%s)", instrument, excluded[instrument] or "no reason given")
            continue

        bars = broker.get_candles(instrument, granularity=GRANULARITY, count=CANDLE_COUNT)
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
                broker.close_position(instrument, in_position)
            continue

        if signal.action == Action.HOLD:
            logger.debug("%s: %s", instrument, signal.reason)
            continue
        if len(open_positions) >= settings.cfd_max_open_positions:
            logger.info("Skipping %s: max open positions reached", instrument)
            continue

        units = risk.position_units(signal.price, signal.stop_price)
        if units <= 0:
            logger.info("Skipping %s: position size computed as 0", instrument)
            continue
        if signal.action == Action.SELL:
            units = -units  # short: negative units

        logger.info(
            "%s %s ~%.5f (stop %.5f, target %.5f) -- %s",
            "BUY" if units > 0 else "SELL", instrument, signal.price,
            signal.stop_price, signal.take_profit_price, signal.reason,
        )
        broker.submit_market_order(instrument, units, signal.stop_price, signal.take_profit_price)
        open_positions[instrument] = {"units": units, "side": "long" if units > 0 else "short"}


if __name__ == "__main__":
    run_once()

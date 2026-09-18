import pandas as pd

from trading.config import settings
from trading.data.market_data import load_watchlist_bars
from trading.execution.broker import AlpacaBroker
from trading.execution.positions import load_positions, record_close, record_open
from trading.execution.state import load_state
from trading.logging_utils import get_logger
from trading.risk.risk_manager import RiskManager
from trading.strategy.base import Action
from trading.strategy.breakout import BreakoutStrategy

logger = get_logger(__name__)


def run_once(lookback_days: int = 150):
    """Evaluate the strategy on the latest bar for each watchlist symbol and
    place/close paper (or, if explicitly enabled, live) orders accordingly.

    Meant to be invoked once per trading day shortly after market open, e.g.
    via cron or a scheduled GitHub Actions workflow.

    Uses Breakout by default -- see run_backtest.py's docstring for why it
    replaced the regime-adaptive strategy. lookback_days defaults to ~150
    calendar days (~100 trading days), comfortably more than the 30-day
    entry window / 14-day ATR window Breakout's indicators need to warm up.

    Buys are notional (dollar-amount) so small accounts can hold fractional
    shares. Alpaca doesn't support bracket orders for fractional quantities,
    so each open position gets two independent DAY orders -- a stop and a
    limit -- re-armed every run (see positions.py and broker.py).
    """
    state = load_state()
    if state.get("paused"):
        logger.info("Bot is paused (state/bot_state.json) -- skipping this run.")
        return

    capital_floor = state.get("capital_floor")
    broker = AlpacaBroker()
    equity = broker.account_equity()
    risk = RiskManager(
        equity=equity,
        risk_per_trade=settings.risk_per_trade,
        max_open_positions=settings.max_open_positions,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        capital_floor=capital_floor,
        ladder=capital_floor is not None,
    )
    if risk.at_or_below_floor():
        logger.info(
            "Equity %.2f is at or below the capital floor %.2f -- no new positions will open this run.",
            equity, capital_floor,
        )

    end = pd.Timestamp.today().normalize()
    start = (end - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    bars = load_watchlist_bars(settings.watchlist, start=start)
    strategy = BreakoutStrategy()

    # 1. Re-check tracked positions: if Alpaca no longer shows the position
    #    open, yesterday's stop or limit order filled -- stop tracking it.
    #    Otherwise cancel any leftover DAY orders and re-arm fresh ones so
    #    the stop-loss / take-profit stay live intraday today too.
    tracked = load_positions()
    for symbol, pos in list(tracked.items()):
        qty = broker.get_position_qty(symbol)
        if qty <= 0:
            logger.info("%s: position closed (stop or target filled)", symbol)
            record_close(symbol)
            continue
        broker.cancel_open_orders(symbol)
        broker.submit_stop_sell(symbol, qty, pos["stop_price"])
        broker.submit_limit_sell(symbol, qty, pos["target_price"])

    tracked = load_positions()
    # Union with Alpaca's actual open positions (not just our tracked ones)
    # so a manual buy or an untracked fill never gets double-bought here.
    open_symbols = set(tracked.keys()) | broker.open_symbols()

    # 2. Evaluate new entries for symbols not already held.
    for symbol, df in bars.items():
        if symbol in open_symbols or df.empty:
            continue
        prepared = strategy.prepare(df)
        last_row = prepared.iloc[-1]
        signal = strategy.signal_for_row(symbol, last_row, in_position=False)

        if signal.action != Action.BUY:
            logger.debug("%s: %s", symbol, signal.reason)
            continue
        if len(open_symbols) >= settings.max_open_positions:
            logger.info("Skipping %s: max open positions reached", symbol)
            continue

        notional = risk.notional_size(signal.price, signal.stop_price)
        if notional <= 0:
            logger.info("Skipping %s: notional size computed as 0", symbol)
            continue

        logger.info(
            "BUY %s ~$%.2f @ ~%.2f (stop %.2f, target %.2f)",
            symbol, notional, signal.price, signal.stop_price, signal.take_profit_price,
        )
        broker.submit_notional_buy(symbol, notional)
        qty = broker.wait_for_position_qty(symbol)
        if qty <= 0:
            logger.info(
                "%s: buy did not fill in time (market likely closed) -- cancelling so it doesn't "
                "fill later untracked; will retry next run",
                symbol,
            )
            broker.cancel_open_orders(symbol)
            continue

        broker.submit_stop_sell(symbol, qty, signal.stop_price)
        broker.submit_limit_sell(symbol, qty, signal.take_profit_price)
        record_open(symbol, qty, signal.stop_price, signal.take_profit_price)
        open_symbols.add(symbol)


if __name__ == "__main__":
    run_once()

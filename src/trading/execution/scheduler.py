import pandas as pd

from trading.config import settings
from trading.data.market_data import load_daily_bars_yfinance, load_watchlist_bars
from trading.execution.broker import AlpacaBroker
from trading.execution.state import load_state
from trading.logging_utils import get_logger
from trading.risk.risk_manager import RiskManager
from trading.strategy.base import Action
from trading.strategy.regime_adaptive import RegimeAdaptiveStrategy

logger = get_logger(__name__)


def run_once(lookback_days: int = 450):
    """Evaluate the strategy on the latest bar for each watchlist symbol and
    place/close paper (or, if explicitly enabled, live) orders accordingly.

    Meant to be invoked once per trading day shortly after market open, e.g.
    via cron or a scheduled GitHub Actions workflow.

    lookback_days defaults to ~450 calendar days (~300 trading days) so the
    200-day indicators used by the regime-adaptive strategy's sub-strategies
    are already warmed up, both for the watchlist symbols and for the
    regime reference symbol.
    """
    if load_state().get("paused"):
        logger.info("Bot is paused (state/bot_state.json) -- skipping this run.")
        return

    broker = AlpacaBroker()
    equity = broker.account_equity()
    risk = RiskManager(
        equity=equity,
        risk_per_trade=settings.risk_per_trade,
        max_open_positions=settings.max_open_positions,
        max_daily_loss_pct=settings.max_daily_loss_pct,
    )

    end = pd.Timestamp.today().normalize()
    start = (end - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    bars = load_watchlist_bars(settings.watchlist, start=start)
    regime_bars = load_daily_bars_yfinance(settings.regime_symbol, start=start)
    strategy = RegimeAdaptiveStrategy(regime_bars=regime_bars)

    open_symbols = broker.open_symbols()
    for symbol, df in bars.items():
        if df.empty:
            continue
        prepared = strategy.prepare(df)
        last_row = prepared.iloc[-1]
        in_position = symbol in open_symbols
        signal = strategy.signal_for_row(symbol, last_row, in_position)

        if signal.action == Action.BUY and not in_position:
            if len(open_symbols) >= settings.max_open_positions:
                logger.info("Skipping %s: max open positions reached", symbol)
                continue
            shares = risk.position_size(signal.price, signal.stop_price)
            if shares <= 0:
                logger.info("Skipping %s: position size computed as 0", symbol)
                continue
            logger.info(
                "BUY %s x%d @ ~%.2f (stop %.2f, target %.2f)",
                symbol, shares, signal.price, signal.stop_price, signal.take_profit_price,
            )
            broker.submit_bracket_buy(symbol, shares, signal.stop_price, signal.take_profit_price)
            open_symbols.add(symbol)

        elif signal.action == Action.SELL and in_position:
            logger.info("SELL %s: %s", symbol, signal.reason)
            broker.close_position(symbol)
            open_symbols.discard(symbol)

        else:
            logger.debug("%s: %s", symbol, signal.reason)


if __name__ == "__main__":
    run_once()

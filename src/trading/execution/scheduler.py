import pandas as pd

from trading.config import settings
from trading.data.earnings import has_upcoming_earnings
from trading.data.market_data import load_watchlist_bars
from trading.execution.broker import AlpacaBroker
from trading.execution.buckets import init_buckets_if_needed, is_blown, rebalance, save_buckets
from trading.execution.positions import load_positions, record_close, record_open
from trading.execution.state import load_state, set_capital_floor, set_milestone_reached
from trading.logging_utils import get_logger
from trading.risk.ratchet import maybe_ratchet_floor
from trading.risk.risk_manager import RiskManager
from trading.strategy.base import Action
from trading.strategy.breakout import BreakoutStrategy
from trading.strategy.mean_reversion import MeanReversionStrategy

logger = get_logger(__name__)

STRATEGY_REGISTRY = {"breakout": BreakoutStrategy, "mean_reversion": MeanReversionStrategy}
BUCKET_MAX_OPEN_POSITIONS = 2


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

    If a capital floor is set (state/bot_state.json), this also checks
    whether equity has grown enough above it to "ratchet" the floor up --
    banking part of the gain as a new, higher protected minimum -- before
    building the risk manager (see risk/ratchet.py). The floor never rises
    past Settings.withdrawal_multiple x the initial floor (e.g. $100 ->
    $200): that's a fixed checkpoint, "the money earmarked to withdraw,"
    not something that keeps climbing.

    Once equity first exceeds Settings.bucket_activation_multiple x the
    initial floor (e.g. $100 -> $300), the capital floor is snapped to
    exactly that $200 withdrawal checkpoint (even if the gradual ratchet
    hadn't quite reached it) and stays there for good, and everything
    above it switches to bucket mode (buckets.py): a "safe" bucket trading
    conservatively and one or more "risk" buckets trading aggressively,
    each sized off its own virtual cash rather than total account equity.
    A risk bucket that loses its cash down near zero ("blown") pauses
    until profit from other risk buckets -- or new growth -- refills it.
    Before that milestone, trading is unchanged: one strategy, one pool.
    """
    state = load_state()
    if state.get("paused"):
        logger.info("Bot is paused (state/bot_state.json) -- skipping this run.")
        return

    capital_floor = state.get("capital_floor")
    broker = AlpacaBroker()
    equity = broker.account_equity()
    initial_floor = state.get("initial_floor")
    withdrawal_checkpoint = initial_floor * settings.withdrawal_multiple if initial_floor else None

    # The floor ratchets up as normal (banking profit) but never past the
    # fixed withdrawal checkpoint (e.g. $200 = 2x the initial $100) -- once
    # bucket mode activates, that checkpoint stays put as "the money that's
    # earmarked to withdraw," and growth beyond it is bucket-managed instead
    # of being folded into more ratcheting.
    if not state.get("milestone_reached"):
        new_floor = maybe_ratchet_floor(
            equity, capital_floor, settings.ratchet_trigger_pct, settings.ratchet_bank_fraction,
            cap=withdrawal_checkpoint,
        )
        if new_floor is not None:
            logger.info(
                "Ratcheting capital floor %.2f -> %.2f (equity %.2f grew >=%.0f%% above the floor; "
                "banking %.0f%% of that gain)",
                capital_floor, new_floor, equity, settings.ratchet_trigger_pct * 100,
                settings.ratchet_bank_fraction * 100,
            )
            set_capital_floor(new_floor)
            capital_floor = new_floor
            state = load_state()

        if (
            initial_floor
            and withdrawal_checkpoint
            and equity > initial_floor * settings.bucket_activation_multiple
        ):
            logger.info(
                "MILESTONE: equity %.2f passed %.0fx the initial floor -- locking the capital floor "
                "at the %.2f withdrawal checkpoint and switching to bucket mode (safe + risk) for "
                "everything above it from here on.",
                equity, settings.bucket_activation_multiple, withdrawal_checkpoint,
            )
            set_capital_floor(withdrawal_checkpoint)  # snap to exactly the checkpoint, even if the
            capital_floor = withdrawal_checkpoint      # gradual ratchet hadn't quite reached it yet
            set_milestone_reached(True)
            state = load_state()

    end = pd.Timestamp.today().normalize()
    start = (end - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    bars = load_watchlist_bars(settings.watchlist, start=start)

    excluded = state.get("excluded_symbols") or {}
    if excluded:
        logger.info("Symbols excluded from new entries (manual): %s", excluded)

    if state.get("milestone_reached"):
        _run_bucket_mode(broker, bars, equity, capital_floor, excluded)
    else:
        _run_single_strategy_mode(broker, bars, equity, capital_floor, excluded)


def _manage_tracked_positions(broker: AlpacaBroker, buckets: dict | None) -> dict:
    """Shared by both modes: for every tracked position, either notice it
    closed (crediting its bucket's cash with the sale proceeds, if it has
    one) or re-arm fresh stop/limit DAY orders so protection stays live
    intraday today too. Returns the (possibly bucket-credited) buckets dict.
    """
    tracked = load_positions()
    for symbol, pos in list(tracked.items()):
        qty = broker.get_position_qty(symbol)
        if qty <= 0:
            bucket_name = pos.get("bucket")
            if buckets is not None and bucket_name and bucket_name in buckets:
                exit_price = broker.get_last_filled_sell_price(symbol)
                proceeds = pos["qty"] * exit_price if exit_price > 0 else 0.0
                buckets[bucket_name]["cash"] += proceeds
                logger.info(
                    "%s: position closed, credited %.2f to bucket '%s' (exit ~%.2f)",
                    symbol, proceeds, bucket_name, exit_price,
                )
            else:
                logger.info("%s: position closed (stop or target filled)", symbol)
            record_close(symbol)
            continue
        broker.cancel_open_orders(symbol)
        broker.submit_stop_sell(symbol, qty, pos["stop_price"])
        broker.submit_limit_sell(symbol, qty, pos["target_price"])
    if buckets is not None:
        save_buckets(buckets)
    return buckets


def _try_enter(broker, symbol, signal, notional, bucket_name=None) -> bool:
    if notional <= 0:
        logger.info("Skipping %s: notional size computed as 0", symbol)
        return False
    if has_upcoming_earnings(symbol):
        logger.info("Skipping %s: earnings report due within the next couple of days", symbol)
        return False
    logger.info(
        "BUY %s ~$%.2f @ ~%.2f (stop %.2f, target %.2f)%s",
        symbol, notional, signal.price, signal.stop_price, signal.take_profit_price,
        f" [bucket {bucket_name}]" if bucket_name else "",
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
        return False

    broker.submit_stop_sell(symbol, qty, signal.stop_price)
    broker.submit_limit_sell(symbol, qty, signal.take_profit_price)
    record_open(symbol, qty, signal.stop_price, signal.take_profit_price, bucket=bucket_name, entry_price=signal.price)
    return True


def _run_single_strategy_mode(broker: AlpacaBroker, bars: dict, equity: float, capital_floor, excluded: dict | None = None):
    risk = RiskManager(
        equity=equity,
        risk_per_trade=settings.risk_per_trade,
        max_open_positions=settings.max_open_positions,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        capital_floor=capital_floor,
        ladder=capital_floor is not None,
    )
    if risk.below_floor():
        logger.info(
            "Equity %.2f is below the capital floor %.2f -- no new positions will open this run.",
            equity, capital_floor,
        )

    strategy = BreakoutStrategy()
    _manage_tracked_positions(broker, buckets=None)

    tracked = load_positions()
    open_symbols = set(tracked.keys()) | broker.open_symbols()

    for symbol, df in bars.items():
        if symbol in open_symbols or df.empty:
            continue
        if excluded and symbol in excluded:
            logger.debug("%s: excluded from new entries (%s)", symbol, excluded[symbol] or "no reason given")
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
        if _try_enter(broker, symbol, signal, notional):
            open_symbols.add(symbol)


def _run_bucket_mode(broker: AlpacaBroker, bars: dict, equity: float, capital_floor: float, excluded: dict | None = None):
    buckets = init_buckets_if_needed()
    buckets = _manage_tracked_positions(broker, buckets=buckets)

    growth_capital = max(0.0, equity - (capital_floor or 0.0))
    buckets = rebalance(buckets, growth_capital, settings.bucket_safe_fraction)
    save_buckets(buckets)

    tracked = load_positions()
    open_symbols = set(tracked.keys()) | broker.open_symbols()
    bucket_open_counts = {name: 0 for name in buckets}
    for pos in tracked.values():
        if pos.get("bucket") in bucket_open_counts:
            bucket_open_counts[pos["bucket"]] += 1

    for bucket_name, bucket in buckets.items():
        strategy_cls = STRATEGY_REGISTRY.get(bucket.get("strategy"), BreakoutStrategy)
        strategy = strategy_cls()
        bucket_risk_per_trade = settings.risk_per_trade * (0.5 if bucket_name == "safe" else 1.0)

        if bucket_name != "safe" and is_blown(bucket):
            logger.info("Bucket '%s' is blown (cash %.2f) -- skipping new entries until refilled", bucket_name, bucket["cash"])
            continue

        risk = RiskManager(equity=bucket["cash"], risk_per_trade=bucket_risk_per_trade, max_open_positions=BUCKET_MAX_OPEN_POSITIONS)

        for symbol, df in bars.items():
            if symbol in open_symbols or df.empty:
                continue
            if excluded and symbol in excluded:
                continue
            if bucket_open_counts.get(bucket_name, 0) >= BUCKET_MAX_OPEN_POSITIONS:
                break

            prepared = strategy.prepare(df)
            last_row = prepared.iloc[-1]
            signal = strategy.signal_for_row(symbol, last_row, in_position=False)
            if signal.action != Action.BUY:
                continue

            notional = risk.notional_size(signal.price, signal.stop_price)
            if notional <= 0:
                continue
            if _try_enter(broker, symbol, signal, notional, bucket_name=bucket_name):
                open_symbols.add(symbol)
                bucket_open_counts[bucket_name] = bucket_open_counts.get(bucket_name, 0) + 1
                buckets[bucket_name]["cash"] -= notional
                save_buckets(buckets)


if __name__ == "__main__":
    run_once()

"""Runs the XM (MT5) CFD/forex trading strategy once, meant to be invoked
periodically (e.g. every 30-60 minutes while the PC is on) by Windows
Task Scheduler on the user's own Windows machine -- see
docs/xm_mt5_setup.md for full setup steps.

Deliberately NOT a persistent always-on daemon. The Deriv bot (see
run_cfd_trading.py) gets its "pause while nothing can run" behavior for
free from GitHub Actions' schedule: simply not firing during an outage;
this script gets the equivalent behavior for free from Windows Task
Scheduler simply not firing while the PC is off -- so there is
deliberately no special pause/resume logic here. Every invocation reads
state/mt5_bot_state.json and state/mt5_trade_log.jsonl, does one
strategy/risk/trade cycle, and exits; the next scheduled tick (whenever
the PC is next on) picks up exactly where the last one left off. Any
stop-loss/take-profit already placed on an open position is enforced by
XM's own server in the meantime, not by this script, so it stays
protected even while the PC is off -- only new entries/exits require the
PC (and this script) to be running.

Completely separate from the Deriv bot: separate broker (MT5Broker, not
DerivBroker), separate state file (state/mt5_bot_state.json, not
state/cfd_bot_state.json), separate safety gate (MT5_ALLOW_LIVE_TRADING,
not CFD_ALLOW_LIVE_TRADING). Reuses the same EmaCrossoverStrategy
unchanged, and CfdRiskManager for its unit-agnostic bookkeeping (open
position count, daily-loss halt, capital floor) -- only position sizing
differs, since MT5 sizes in lots via MT5Broker.size_to_lots(), not
Deriv's stake+multiplier (see risk.py's stake_and_limits()).

Usage: python scripts/run_mt5_service.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.mt5_broker import (  # noqa: E402
    MT5Broker,
    MT5LiveAccountError,
    MT5NotConnectedError,
    MT5RequestError,
)
from trading.cfd.mt5_state import append_trade_log, load_state, set_capital_floor  # noqa: E402
from trading.cfd.risk import CfdRiskManager  # noqa: E402
from trading.cfd.mean_reversion import MeanReversionStrategy  # noqa: E402
from trading.cfd.regime import RANGING, classify_regime  # noqa: E402
from trading.cfd.strategy import EmaCrossoverStrategy  # noqa: E402
from trading.config import settings  # noqa: E402
from trading.logging_utils import get_logger  # noqa: E402
from trading.strategy.base import Action  # noqa: E402

logger = get_logger(__name__)

CANDLE_COUNT = 200  # comfortably more than slow_span=34 + atr_window=14 warmup
# Regime is read from the next timeframe up, as in Deriv's virtual accounts
# (context timeframes M15->M5, H1->M15, ...).
_REGIME_TIMEFRAME = {"M1": "M5", "M5": "M15", "M15": "H1", "H1": "H4"}


def _make_strategy(name: str):
    """MT5_STRATEGY picks the entry logic; both share prepare()/signal_for_row().
    Unknown names raise (surfaced as a misconfiguration) rather than silently
    falling back to a strategy the user didn't ask for."""
    strategies = {"ema_crossover": EmaCrossoverStrategy, "mean_reversion": MeanReversionStrategy}
    try:
        return strategies[name]()
    except KeyError:
        raise RuntimeError(f"MT5_STRATEGY must be one of {sorted(strategies)} (got {name!r})") from None


def _risk_gate_open(risk: CfdRiskManager) -> bool:
    """Re-derives CfdRiskManager._can_open_new_position()'s condition from
    its public surface (halted, open_positions, max_open_positions,
    below_floor()) instead of reaching into its private method -- this
    file plugs CfdRiskManager in from outside risk.py, not as a subclass,
    so it only uses what risk.py already exposes publicly."""
    return not risk.halted and risk.open_positions < risk.max_open_positions and not risk.below_floor()


def run_once() -> None:
    state = load_state()
    if state.get("paused"):
        logger.info("MT5 bot is paused (state/mt5_bot_state.json) -- skipping this run.")
        return

    try:
        broker = MT5Broker()
    except RuntimeError as exc:
        # Misconfiguration (missing credentials, live server without the
        # explicit opt-in) -- surface loudly, this is not a "try again
        # later" condition like MT5NotConnectedError below.
        logger.error("MT5 bot misconfigured: %s", exc)
        return

    try:
        account = broker.connect()
    except MT5NotConnectedError as exc:
        # Normal right after boot, or if the XM MT5 terminal hasn't been
        # opened/logged in yet -- log and exit cleanly rather than
        # treating this as a crash. The next scheduled tick (whenever the
        # PC is next on and MT5 is reachable) will try again.
        logger.info("MT5 not reachable this run (%s) -- will retry next scheduled tick.", exc)
        return
    except MT5LiveAccountError as exc:
        logger.error("MT5 bot misconfigured: %s", exc)
        return

    try:
        equity = broker.account_equity()
        logger.info("Connected to MT5 account %s on %s -- equity %.2f", account["login"], account["server"], equity)

        capital_floor = state.get("capital_floor")
        if capital_floor is None:
            # First run: protect the starting balance by default, same as
            # the Deriv bot's own first-run behavior (see scheduler.py).
            set_capital_floor(equity)
            capital_floor = equity
            logger.info("First run: capital floor set to starting equity %.2f", equity)

        risk = CfdRiskManager(
            equity=equity,
            risk_per_trade=settings.mt5_risk_per_trade,
            max_open_positions=settings.mt5_max_open_positions,
            max_daily_loss_pct=settings.mt5_max_daily_loss_pct,
            capital_floor=capital_floor,
        )
        if risk.below_floor():
            logger.info("Equity %.2f is below the capital floor %.2f -- no new entries this run.", equity, capital_floor)

        excluded = state.get("excluded_instruments") or {}
        open_positions = broker.open_positions()
        strategy = _make_strategy(settings.mt5_strategy)
        logger.info("Strategy: %s", settings.mt5_strategy)

        for requested_symbol in settings.mt5_instruments:
            if requested_symbol in excluded:
                logger.debug("%s: excluded (%s)", requested_symbol, excluded[requested_symbol] or "no reason given")
                continue

            try:
                symbol = broker.resolve_symbol(requested_symbol)
            except MT5RequestError as exc:
                logger.warning("%s: symbol lookup failed (%s) -- skipping this instrument.", requested_symbol, exc)
                continue

            bars = broker.get_candles(symbol, count=CANDLE_COUNT, timeframe=settings.mt5_timeframe)
            if len(bars) < 2:
                logger.debug("%s: not enough candles yet", symbol)
                continue

            prepared = strategy.prepare(bars)
            row, prev_row = prepared.iloc[-1], prepared.iloc[-2]
            position = open_positions.get(symbol)
            in_position = position["side"] if position else None

            signal = strategy.signal_for_row(symbol, row, prev_row, in_position)

            if in_position is not None:
                is_exit = (in_position == "long" and signal.action == Action.SELL) or (
                    in_position == "short" and signal.action == Action.BUY
                )
                age = position.get("age_hours")
                max_hold = settings.mt5_max_hold_hours
                timed_out = max_hold > 0 and age is not None and age >= max_hold
                if timed_out and not is_exit:
                    signal.reason = f"max hold time reached ({age:.1f}h >= {max_hold:g}h) -- day-trade flatten"
                if is_exit or timed_out:
                    logger.info("%s: closing %s position (%s)", symbol, in_position, signal.reason)
                    pnl = position.get("profit", 0.0)  # live floating P&L at the moment of close -- see open_positions() docstring
                    result = broker.close_position({**position, "symbol": symbol})
                    append_trade_log(
                        {"event": "close", "symbol": symbol, "side": in_position, "reason": signal.reason, "pnl": pnl, **result}
                    )
                    risk.register_close(pnl=pnl)
                continue

            if signal.action == Action.HOLD:
                logger.debug("%s: %s", symbol, signal.reason)
                continue
            if settings.mt5_strategy == "mean_reversion":
                # Deriv's forward data: mean_reversion won ~65% in ranging
                # markets but is only suited to those (suited_regimes in
                # cfd_strategy_registry.json), so skip entries otherwise.
                regime = classify_regime(
                    broker.get_candles(symbol, count=CANDLE_COUNT, timeframe=_REGIME_TIMEFRAME.get(settings.mt5_timeframe.upper(), settings.mt5_timeframe))
                )
                if regime != RANGING:
                    logger.info("Skipping %s entry: regime is %r, mean_reversion only trades 'ranging'", symbol, regime)
                    continue
            if not _risk_gate_open(risk):
                logger.info(
                    "Skipping %s: risk gate closed (halted=%s open_positions=%d/%d below_floor=%s)",
                    symbol, risk.halted, risk.open_positions, risk.max_open_positions, risk.below_floor(),
                )
                continue

            stop_distance = abs(signal.price - signal.stop_price) if signal.stop_price is not None else 0.0
            if stop_distance <= 0:
                logger.info("Skipping %s: degenerate stop distance", symbol)
                continue

            risk_amount = equity * settings.mt5_risk_per_trade
            lots = broker.size_to_lots(symbol, risk_amount, stop_distance)
            if lots <= 0:
                logger.info("Skipping %s: lot size computed as 0 (risk budget below the broker's minimum lot)", symbol)
                continue

            side = "long" if signal.action == Action.BUY else "short"
            logger.info(
                "%s %s lots=%.2f (stop=%.5f target=%.5f) -- %s",
                side.upper(), symbol, lots, signal.stop_price, signal.take_profit_price, signal.reason,
            )
            result = broker.open_position(symbol, side, lots, signal.stop_price, signal.take_profit_price)
            open_positions[symbol] = {"ticket": result["ticket"], "side": side, "lots": lots}
            append_trade_log({"event": "open", "symbol": symbol, "side": side, "reason": signal.reason, **result})
            risk.register_open()
    finally:
        broker.close()


if __name__ == "__main__":
    run_once()

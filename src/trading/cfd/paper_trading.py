"""Paper Trading (CFD) -- src/trading/cfd/paper_trading.py

Runs every strategy in the Strategy Registry's PAPER lifecycle state
through the SAME regime-gated signal logic the live scheduler uses for
ACTIVE strategies, on the SAME real-time candles -- but never places a
real (or demo-account) Deriv order. Each paper position is tracked
locally (entry price, stop, target) and closed when a later candle's
high/low crosses that stop/target, or the strategy's own exit signal
fires -- exactly the check trading.cfd.backtest.CfdBacktestEngine already
does for a historical backtest, run incrementally across live runs
instead of once over history, since there's no real broker managing a
paper position's stop-loss/take-profit for us.

This is the "Paper Trading" stage of docs/VISION.md's strategy pipeline:
real forward-looking validation on data a backtest never saw, the step
between automated validation (trading.cfd.research_lab, which only ever
lands a candidate at VALIDATED) and a human's decision to promote a
strategy to ACTIVE. Advancing a strategy INTO PAPER, and promoting it OUT
to ACTIVE, are both still deliberate, audited `cfd_cli.py
promote-strategy` calls -- this module only runs whatever's already been
placed in PAPER; it never changes lifecycle state itself.

Each PAPER strategy tracks its own independent virtual equity, seeded at
CFD_VIRTUAL_STARTING_CAPITAL the first time it's ever evaluated -- paper
trading is a parallel simulation that never shares the real (or
virtual-real) account's risk pool or position count with whatever is
actually ACTIVE.

Deliberately NOT modeled (kept simple, on purpose): a cross-instrument
max-open-positions cap or a daily-loss circuit breaker for paper
strategies -- those govern real capital at risk, which paper trading has
none of. What paper trading is actually for -- signal quality, and
whether CfdRiskManager's per-trade sizing (including the min-stake SKIP
TRADE guard) behaves sensibly against real forward data -- is still
fully exercised per trade.
"""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from trading.cfd.risk import CfdRiskManager
from trading.cfd.state import (
    get_paper_equity,
    get_paper_position,
    next_paper_contract_id,
    pop_paper_position,
    set_paper_equity,
    set_paper_position,
)
from trading.cfd.strategy_registry import LifecycleState, list_by_state
from trading.cfd.trade_log import TradeRecord, record_trade
from trading.cfd.virtual_accounts import account_for_strategy, ensure_virtual_accounts, record_virtual_close
from trading.config import settings
from trading.logging_utils import get_logger
from trading.strategy.base import Action

logger = get_logger(__name__)

PAPER_LOG_PATH = Path(__file__).resolve().parents[3] / "state" / "cfd_paper_trades.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pnl(side: str, entry: float, exit_price: float, stake: float, multiplier: int) -> float:
    """Same shape as CfdBacktestEngine._pnl -- capped at -stake, matching
    Deriv Multipliers' real capped-loss guarantee, even though this is a
    simulated fill with no real contract behind it."""
    pct_move = (exit_price - entry) / entry if side == "long" else (entry - exit_price) / entry
    return max(stake * multiplier * pct_move, -stake)


def _check_price_exit(position: dict, row: pd.Series) -> tuple:
    """Returns (exit_reason, exit_price) if this bar's high/low crosses
    the position's stored stop or target -- no-slippage, exact-level
    fills, matching CfdBacktestEngine's and Deriv's own guaranteed-stop
    assumption. Returns (None, None) if price alone doesn't close it
    (still separately checked against the strategy's own exit signal by
    the caller)."""
    side = position["side"]
    stop, target = position["stop_price"], position["target_price"]
    hit_stop = (side == "long" and row["low"] <= stop) or (side == "short" and row["high"] >= stop)
    hit_target = (side == "long" and row["high"] >= target) or (side == "short" and row["low"] <= target)
    if hit_stop:
        return "stop_loss", stop
    if hit_target:
        return "take_profit", target
    return None, None


def run_paper_trading(instrument: str, bars: pd.DataFrame, regime: str) -> None:
    """Evaluates every PAPER-state strategy against this instrument's
    already-fetched candles (reused from the live scheduler's own fetch
    for this instrument -- no extra API calls). Manages any existing
    paper position to its exit regardless of the current regime (an open
    position isn't abandoned just because the regime shifted -- same
    principle as the live scheduler's real positions), and opens a new
    one only when the strategy's suited_regimes matches the current
    regime, mirroring exactly how trading.cfd.selector gates ACTIVE
    entries."""
    if len(bars) < 2:
        return

    virtual_accounts = ensure_virtual_accounts()
    for entry in list_by_state(LifecycleState.PAPER):
        strategy_tag = f"{entry.name}@{entry.version}"
        virtual_account_id = account_for_strategy(strategy_tag)
        virtual_account = virtual_accounts.get(virtual_account_id, {}) if virtual_account_id else {}
        strategy = entry.build()
        prepared = strategy.prepare(bars)
        row, prev_row = prepared.iloc[-1], prepared.iloc[-2]

        position = get_paper_position(strategy_tag, instrument)

        if position is not None:
            in_position = position["side"]
            price_exit_reason, price_exit_price = _check_price_exit(position, row)
            signal = strategy.signal_for_row(instrument, row, prev_row, in_position)
            signal_exit = (in_position == "long" and signal.action == Action.SELL) or (
                in_position == "short" and signal.action == Action.BUY
            )

            if price_exit_reason is None and not signal_exit:
                continue

            exit_reason = price_exit_reason or f"signal_exit: {signal.reason}"
            exit_price = price_exit_price if price_exit_reason else signal.price
            pnl = round(_pnl(in_position, position["entry_price"], exit_price, position["stake"], position["multiplier"]), 2)
            equity_before = get_paper_equity(strategy_tag, settings.cfd_virtual_starting_capital)
            equity_after = round(equity_before + pnl, 2)
            set_paper_equity(strategy_tag, equity_after)
            pop_paper_position(strategy_tag, instrument)

            record_trade(
                TradeRecord(
                    contract_id=position["contract_id"],
                    instrument=instrument,
                    strategy=strategy_tag,
                    side=in_position,
                    entry_time=position["entry_time"],
                    exit_time=_now_iso(),
                    entry_price=position["entry_price"],
                    stake=position["stake"],
                    risk_amount=position["risk_amount"],
                    exit_price=exit_price,
                    pnl=pnl,
                    equity_before=equity_before,
                    equity_after=equity_after,
                    exit_reason=f"paper: {exit_reason}",
                    regime=position.get("regime"),
                    virtual_account_id=position.get("virtual_account_id"),
                    horizon=position.get("horizon"),
                    entry_timeframe=position.get("entry_timeframe"),
                    context_timeframes=position.get("context_timeframes"),
                ),
                path=PAPER_LOG_PATH,
            )
            if position.get("virtual_account_id"):
                record_virtual_close(position["virtual_account_id"], pnl)
            logger.info("PAPER %s: closed %s %s (pnl=%.2f, %s)", strategy_tag, instrument, in_position, pnl, exit_reason)
            continue

        if regime not in (entry.suited_regimes or []):
            continue

        signal = strategy.signal_for_row(instrument, row, prev_row, None)
        if signal.action == Action.HOLD:
            continue

        equity = get_paper_equity(strategy_tag, settings.cfd_virtual_starting_capital)
        risk = CfdRiskManager(equity=equity, risk_per_trade=settings.cfd_risk_per_trade, min_stake=settings.cfd_min_stake)
        stake, stop_loss_amount, _ = risk.stake_and_limits(signal.price, signal.stop_price, signal.take_profit_price)
        if stake <= 0:
            logger.debug("PAPER %s: skipping %s -- stake computed as 0", strategy_tag, instrument)
            continue

        side = "long" if signal.action == Action.BUY else "short"
        contract_id = next_paper_contract_id()
        set_paper_position(
            strategy_tag,
            instrument,
            {
                "contract_id": contract_id,
                "side": side,
                "entry_price": signal.price,
                "stop_price": signal.stop_price,
                "target_price": signal.take_profit_price,
                "stake": stake,
                "multiplier": risk.multiplier,
                "risk_amount": stop_loss_amount,
                "entry_time": _now_iso(),
                "regime": regime,
                "virtual_account_id": virtual_account_id,
                "horizon": virtual_account.get("horizon", "swing"),
                "entry_timeframe": virtual_account.get("entry_timeframe", "H1"),
                "context_timeframes": virtual_account.get("context_timeframes", ["H4", "H1"]),
            },
        )
        logger.info("PAPER %s: opened %s %s stake=%.2f (regime=%s)", strategy_tag, side.upper(), instrument, stake, regime)


def run_virtual_account_paper(account_id: str, instrument: str, bars: pd.DataFrame, regime: str, strategy) -> None:
    """Run one PAPER virtual account on genuine forward candles.

    State is keyed by account_id (not strategy tag), so several timeframe/account
    experiments may use the same strategy without contaminating one another.
    This is simulation only and never calls the broker order API.
    """
    if len(bars) < 2:
        return
    accounts = ensure_virtual_accounts()
    account = accounts.get(account_id)
    if not account or account.get("execution_tier") != "PAPER":
        return

    strategy_tag = account.get("strategy_tag") or strategy.name
    state_key = f"virtual:{account_id}"
    prepared = strategy.prepare(bars)
    row, prev_row = prepared.iloc[-1], prepared.iloc[-2]
    position = get_paper_position(state_key, instrument)

    if position is not None:
        side = position["side"]
        price_exit_reason, price_exit_price = _check_price_exit(position, row)
        signal = strategy.signal_for_row(instrument, row, prev_row, side)
        signal_exit = (side == "long" and signal.action == Action.SELL) or (
            side == "short" and signal.action == Action.BUY
        )
        if price_exit_reason is None and not signal_exit:
            return
        exit_reason = price_exit_reason or f"signal_exit: {signal.reason}"
        exit_price = price_exit_price if price_exit_reason else signal.price
        pnl = round(_pnl(side, position["entry_price"], exit_price, position["stake"], position["multiplier"]), 2)
        pop_paper_position(state_key, instrument)
        row_account = record_virtual_close(account_id, pnl)
        set_paper_equity(state_key, row_account["equity"])
        record_trade(
            TradeRecord(
                contract_id=position["contract_id"], instrument=instrument, strategy=strategy_tag,
                side=side, entry_time=position["entry_time"], exit_time=_now_iso(),
                entry_price=position["entry_price"], stake=position["stake"],
                risk_amount=position["risk_amount"], exit_price=exit_price, pnl=pnl,
                equity_before=position["equity_before"], equity_after=row_account["equity"],
                exit_reason=f"paper-forward: {exit_reason}", regime=position.get("regime"),
                virtual_account_id=account_id, horizon=account.get("horizon"),
                entry_timeframe=position.get("entry_timeframe"),
                context_timeframes=account.get("context_timeframes"),
            ), path=PAPER_LOG_PATH,
        )
        logger.info("PAPER-FORWARD %s: closed %s %s pnl=%.2f", account_id, instrument, side, pnl)
        return

    signal = strategy.signal_for_row(instrument, row, prev_row, None)
    if signal.action == Action.HOLD:
        return
    equity = float(account.get("equity", account.get("starting_equity", settings.cfd_virtual_starting_capital)))
    risk_fraction = 0.20 if account.get("horizon") == "ultra_highrisk" else settings.cfd_risk_per_trade
    risk = CfdRiskManager(equity=equity, risk_per_trade=risk_fraction, min_stake=settings.cfd_min_stake)
    stake, stop_loss_amount, _ = risk.stake_and_limits(
        signal.price, signal.stop_price, signal.take_profit_price,
        risk_per_trade_override=risk_fraction,
    )
    if stake <= 0:
        return
    side = "long" if signal.action == Action.BUY else "short"
    set_paper_position(state_key, instrument, {
        "contract_id": next_paper_contract_id(), "side": side,
        "entry_price": signal.price, "stop_price": signal.stop_price,
        "target_price": signal.take_profit_price, "stake": stake,
        "multiplier": risk.multiplier, "risk_amount": stop_loss_amount,
        "entry_time": _now_iso(), "equity_before": equity, "regime": regime,
        "virtual_account_id": account_id, "horizon": account.get("horizon"),
        "entry_timeframe": account.get("entry_timeframe"),
        "context_timeframes": account.get("context_timeframes"),
    })
    set_paper_equity(state_key, equity)
    logger.info("PAPER-FORWARD %s: opened %s %s stake=%.2f tf=%s", account_id, side, instrument, stake, account.get("entry_timeframe"))

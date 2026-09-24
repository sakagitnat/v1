"""Experimental DEMO timeframe quotas, closed before the UTC window ends.

The simple candle-direction baseline is not a qualified profitable strategy.
All writers must share the cfd-trading workflow concurrency group.
"""
import asyncio
import json
import math
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from trading.cfd import state
from trading.cfd.broker import DerivBroker
from trading.cfd.capital import equity_for_account
from trading.cfd.portfolio_risk import OpenRiskPosition, PortfolioRiskCeilings, check_new_position
from trading.cfd.trade_log import TradeRecord, load_trades, record_trade
from trading.cfd.virtual_accounts import ensure_virtual_accounts
from trading.config import settings

SPECS = {
    "quota_30m_forward": (1800, "M30", 1800),
    "quota_h1_forward": (3600, "H1", 3600),
    "quota_h4_forward": (14400, "H4", 14400),
    "quota_d1_forward": (86400, "D1", 86400),
}
STAKE, STOP, TARGET, MULTIPLIER = 1.0, 0.25, 0.50, 100
LOG_PATH = Path(__file__).resolve().parents[3] / "state/cfd_quota_events.jsonl"


def now():
    return datetime.now(timezone.utc)


def event(outcome, **fields):
    row = {"timestamp": now().isoformat(), "run_id": os.getenv("GITHUB_RUN_ID"),
           "outcome": outcome, **fields}
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(row, allow_nan=False) + "\n")
    print("QUOTA_RESULT=" + json.dumps(row, allow_nan=False), flush=True)
    return row


def profit_from_sale(response, contract_id, cost):
    """New Deriv sell response uses sold_for, not sell_price."""
    sale = response.get("sell") or {}
    if str(sale.get("contract_id")) != str(contract_id):
        raise RuntimeError("Sell response contract does not match")
    value = sale.get("sold_for")
    if isinstance(value, bool):
        raise RuntimeError("Invalid sell proceeds")
    try:
        proceeds = float(value)
    except (TypeError, ValueError):
        raise RuntimeError("Sell proceeds unavailable") from None
    if not math.isfinite(proceeds) or proceeds < 0 or not math.isfinite(cost) or cost <= 0:
        raise RuntimeError("Invalid sell accounting")
    return round(proceeds - cost, 2)


def flush_settlements():
    """Replay the state outbox without appending a second trade row."""
    known = {int(r["contract_id"]) for r in load_trades()}
    for cid, row in state.load_state().get("quota_settlements", {}).items():
        if int(cid) not in known:
            record_trade(TradeRecord(**row))
            known.add(int(cid))


def commit_close(record, window_id):
    """Ledger credit, window marker, outbox and metadata removal in one write."""
    s = state.load_state()
    key = str(record.contract_id)
    outbox = s.setdefault("quota_settlements", {})
    if key in outbox:
        if outbox[key]["pnl"] != record.pnl or outbox[key]["virtual_account_id"] != record.virtual_account_id:
            raise RuntimeError("Conflicting settlement evidence")
        flush_settlements()
        return
    if record.pnl is None or not math.isfinite(record.pnl):
        raise RuntimeError("Cannot settle unknown profit")
    row = s["virtual_accounts"][record.virtual_account_id]
    row["equity"] = round(row["equity"] + record.pnl, 2)
    row["realized_pnl"] = round(row.get("realized_pnl", 0) + record.pnl, 2)
    row["closed_trades"] = row.get("closed_trades", 0) + 1
    row["wins"] = row.get("wins", 0) + int(record.pnl > 0)
    row["losses"] = row.get("losses", 0) + int(record.pnl < 0)
    row["high_water_mark"] = max(row.get("high_water_mark", 100), row["equity"])
    record.equity_after = row["equity"]
    outbox[key] = asdict(record)
    s.setdefault("quota_windows", {})[record.virtual_account_id] = {
        "window_id": window_id, "contract_id": record.contract_id, "closed_at": record.exit_time}
    s.setdefault("open_trades", {}).pop(key, None)
    state._write_state(s)
    flush_settlements()


async def close_tracked(broker, cid, meta):
    was_open = cid in await broker.open_contract_ids()
    if was_open:
        response = await broker.close_position(cid)  # no blind sell retry
        pnl = profit_from_sale(response, cid, float(meta.get("buy_price", meta["stake"])))
    else:
        pnl = await broker.settled_profit(cid)
    record = TradeRecord(
        contract_id=cid, instrument=meta["instrument"], strategy=meta["strategy"],
        side=meta["side"], entry_time=meta["entry_time"], exit_time=now().isoformat(),
        entry_price=meta["entry_price"], stake=meta["stake"], risk_amount=meta["risk_amount"],
        pnl=pnl, equity_before=meta["equity_before"],
        exit_reason=("closed_externally; broker settlement verified" if not was_open else
                     "quota_window_deadline" if meta.get("close_at") else "forced_quota_execution_probe"),
        regime=meta.get("regime", "forced_quota_research"), leg="quota", virtual_account_id=meta["virtual_account_id"],
        horizon=meta["horizon"], entry_timeframe=meta["entry_timeframe"],
        context_timeframes=meta["context_timeframes"],
    )
    commit_close(record, meta["quota_window"])
    period = SPECS[record.virtual_account_id][0]
    late = now().timestamp() >= (meta["quota_window"] + 1) * period
    return event("CLOSED_LATE" if late else "CLOSED", account=record.virtual_account_id,
                 contract_id=cid, instrument=record.instrument, pnl=pnl,
                 window_id=meta["quota_window"], holding_seconds=(now()-datetime.fromisoformat(meta["entry_time"])).total_seconds())


async def run_quotas():
    if settings.cfd_allow_live_trading:
        raise RuntimeError("Quota research requires DEMO mode")
    ensure_virtual_accounts()
    flush_settlements()
    broker = DerivBroker()
    results = []
    try:
        account = await broker.connect()
        if account.get("account_type") != "demo" or account.get("currency") != "USD":
            raise RuntimeError("Quota research requires a USD DEMO account")
        # Recover existing quota contracts first, even when new entries are paused.
        for cid, meta in state.list_open_trades().items():
            if "quota_window" in meta:
                if not meta.get("close_at") or now().timestamp() >= meta["close_at"] or int(cid) not in await broker.open_contract_ids():
                    results.append(await close_tracked(broker, int(cid), meta))
        active = await broker.list_active_symbols()
        available = {r.get("underlying_symbol", r.get("symbol")) for r in active
                     if r.get("exchange_is_open") == 1 and not r.get("is_trading_suspended")}
        candidates = [x for x in settings.cfd_instruments if x in available]
        for aid, (period, timeframe, granularity) in SPECS.items():
            s = state.load_state()
            current = now()
            window = int(current.timestamp()) // period
            observation = s.setdefault("quota_evaluation_windows", {}).get(aid)
            if observation is not None and window > observation + 1:
                event("EVALUATION_GAP", account=aid, previous_window=observation,
                      current_window=window, unobserved_windows=window-observation-1)
            s["quota_evaluation_windows"][aid] = window
            state._write_state(s)
            if any(m.get("virtual_account_id") == aid for m in s.get("open_trades", {}).values()):
                results.append(event("HOLDING", account=aid, window_id=window)); continue
            if s.get("quota_windows", {}).get(aid, {}).get("window_id") == window:
                results.append(event("ALREADY_COMPLETED", account=aid, window_id=window)); continue
            if (window+1)*period-current.timestamp() < 180:
                results.append(event("WINDOW_TOO_SHORT", account=aid, window_id=window)); continue
            if s.get("paused") or s.get("pending_entries"):
                results.append(event("RECOVERY_OR_PAUSE_BLOCKED", account=aid)); continue
            row = s["virtual_accounts"][aid]
            day = current.date().isoformat()
            daily = row.get("quota_daily", {})
            if daily.get("date") != day:
                row["quota_daily"] = daily = {"date": day, "start_equity": row["equity"]}
                state._write_state(s)
            if row["equity"] < STAKE or row.get("ruined") or row["equity"] <= daily["start_equity"] * (1-settings.cfd_max_daily_loss_pct):
                results.append(event("ACCOUNT_RISK_BLOCKED", account=aid)); continue
            symbols = [x for x in candidates if x not in s.get("excluded_instruments", {})]
            if not symbols:
                results.append(event("MARKET_CLOSED_OR_EXCLUDED", account=aid)); continue
            symbol = symbols[window % len(symbols)]
            if granularity:
                data = await broker.get_candles(symbol, granularity, 80)
                data = data[data.index + __import__("pandas").Timedelta(seconds=granularity) <= current]
                column = "close"
            else:
                data = await broker.get_ticks(symbol, 80)
                column = "price"
            if len(data) < 2 or (current-data.index[-1].to_pydatetime()).total_seconds() > max(120, granularity*2):
                results.append(event("STALE_OR_MISSING_DATA", account=aid)); continue
            prices = data[column].astype(float)
            side = "long" if prices.iloc[-1] >= prices.iloc[-2] else "short"
            tracked = state.list_open_trades()
            actual = await broker.open_contract_ids()
            if actual != {int(cid) for cid in tracked}:
                results.append(event("RECONCILIATION_REQUIRED", account=aid)); continue
            balance = await broker.account_equity()
            equity = equity_for_account(balance + sum(m["stake"] for m in tracked.values()), "demo", s.get("broker_baseline"), settings.cfd_virtual_starting_capital)
            if s.get("broker_baseline") is None:
                results.append(event("BASELINE_REQUIRED", account=aid)); continue
            dr = s.get("daily_risk_tracking", {})
            if (dr.get("date") == day and (dr.get("halted") or equity <= dr.get("start_equity", equity)*(1-settings.cfd_max_daily_loss_pct))) or (s.get("capital_floor") is not None and equity < s["capital_floor"]):
                results.append(event("PORTFOLIO_HALT", account=aid)); continue
            if len(actual) >= settings.cfd_max_open_positions or STOP > min(equity, row["equity"])*settings.cfd_max_risk_per_trade_ceiling:
                results.append(event("POSITION_OR_TRADE_RISK_BLOCKED", account=aid)); continue
            positions = [OpenRiskPosition(int(cid), m["instrument"], m["side"], m.get("risk_amount", m["stake"]), m["stake"]*m.get("multiplier", 0)) for cid,m in tracked.items()]
            ceilings = PortfolioRiskCeilings(settings.cfd_max_thesis_risk_pct, settings.cfd_max_correlated_risk_pct, settings.cfd_max_portfolio_risk_pct, settings.cfd_max_exposure_multiple)
            reason = check_new_position(positions, symbol, side, STOP, STAKE*MULTIPLIER, equity, ceilings)
            if reason or sum(p.risk_amount for p in positions)+STOP > 1.50:
                results.append(event("RISK_BLOCKED", account=aid, reason=reason or "research risk budget")); continue
            meta = dict(instrument=symbol, strategy=aid+"@timeframe_v2", side=side,
                        entry_time=now().isoformat(), entry_price=float(prices.iloc[-1]),
                        stake=STAKE, risk_amount=STOP, multiplier=MULTIPLIER,
                        equity_before=row["equity"], regime="forced_quota_research", leg="quota",
                        broker_managed_only=True, forced_quota=True, experimental=True,
                        virtual_account_id=aid, horizon=str(period)+"s_window",
                        entry_timeframe=timeframe, context_timeframes=[timeframe], quota_window=window,
                        close_at=(window+1)*period-120,
                        entry_reason="experimental direction of last two completed timeframe candles")
            row.update(entry_timeframe=timeframe, context_timeframes=[timeframe],
                       strategy_tag=meta["strategy"], label=timeframe+" experimental timeframe quota")
            state._write_state(s)
            state.set_pending_entry(symbol, {"legs": [meta], "quota_intent": True})
            bought = await broker.submit_multiplier_order(symbol, side, STAKE, MULTIPLIER, STOP, TARGET)
            cid = int(bought["buy"]["contract_id"])
            meta["buy_price"] = float(bought["buy"].get("buy_price", STAKE))
            state.record_open_trade(cid, meta)
            state.clear_pending_entry(symbol)
            results.append(event("OPENED", account=aid, contract_id=cid, instrument=symbol, window_id=window,
                                 timeframe=timeframe, strategy=meta["strategy"], close_at=meta["close_at"]))
    except Exception as exc:
        event("ERROR", error=type(exc).__name__)  # no sensitive response bodies
        raise
    finally:
        await broker.close()
    return results

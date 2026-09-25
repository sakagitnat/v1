"""Virtual sub-account laboratory for CFD demo research.

The Deriv demo broker balance is one shared account. These sub-accounts are
logical ledgers only: each starts at $100 and is used to keep strategy/horizon
experiments statistically separate. They DO NOT bypass the master Portfolio
Risk Governor and they do not increase its hard ceilings.

Execution tiers:
- ACTIVE_DEMO: may be attached to a strategy already allowed to send demo orders.
- PAPER: simulated fills only.
- SHADOW: signals/market observations only; no synthetic P&L claims.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional
import json
from datetime import datetime, timezone
from pathlib import Path

from trading.cfd import state as _state
from trading.cfd.state import load_state, set_virtual_accounts
from trading.cfd.trade_log import TradeRecord, load_trades, record_trade
from trading.logging_utils import get_logger

logger = get_logger(__name__)


ACTIVE_DEMO = "ACTIVE_DEMO"
PAPER = "PAPER"
SHADOW = "SHADOW"
RUIN_LOG_PATH = Path(__file__).resolve().parents[3] / "state" / "cfd_virtual_account_ruin_log.jsonl"


@dataclass(frozen=True)
class VirtualAccountSpec:
    account_id: str
    label: str
    starting_equity: float
    execution_tier: str
    horizon: str
    entry_timeframe: str
    context_timeframes: tuple[str, ...]
    strategy_tag: Optional[str] = None


DEFAULT_VIRTUAL_ACCOUNTS = (
    VirtualAccountSpec("core_h1", "Core H1 trend", 100.0, ACTIVE_DEMO, "core", "H1", ("H4", "H1"), "ema_crossover@v1"),
    # Timeframe-champion accounts (docs/ARCHITECTURE_AUDIT.md, 2026-09-24):
    # one isolated $100 account per timeframe, each running whichever
    # strategy trading.cfd.timeframe_champion has currently assigned it --
    # unassigned (strategy_tag=None) until something clears TRAIN/TEST/
    # walk-forward at that timeframe's own granularity. core_h1 above is
    # already H1's champion (wired into scheduler.run_once() since before
    # this concept had a name); these three cover the other timeframes.
    VirtualAccountSpec("champion_m30", "M30 timeframe champion", 100.0, ACTIVE_DEMO, "champion", "M30", ("H4", "H1", "M30"), None),
    VirtualAccountSpec("champion_h4", "H4 timeframe champion", 100.0, ACTIVE_DEMO, "champion", "H4", ("D1", "H4"), None),
    VirtualAccountSpec("champion_d1", "D1 timeframe champion", 100.0, ACTIVE_DEMO, "champion", "D1", ("D1",), None),
    VirtualAccountSpec("breakout_h1", "H1 breakout forward lab", 100.0, PAPER, "swing", "H1", ("H4", "H1"), "donchian_breakout@v2"),
    VirtualAccountSpec("intraday_m15", "M15 intraday research", 100.0, SHADOW, "intraday", "M15", ("H4", "H1", "M15")),
    VirtualAccountSpec("intraday_m5", "M5 intraday research", 100.0, SHADOW, "intraday", "M5", ("H1", "M15", "M5")),
    VirtualAccountSpec("starter_m5_probe", "M5 starter demo probe", 100.0, ACTIVE_DEMO, "intraday", "M5", ("H1", "M15", "M5"), "starter_intraday@v0"),
    VirtualAccountSpec("scalp_m1", "M1 execution research", 100.0, ACTIVE_DEMO, "scalp", "M1", ("M15", "M5", "M1"), "starter_m1@v0"),
    VirtualAccountSpec("scalp_ticks", "Tick-seconds execution research", 100.0, ACTIVE_DEMO, "scalp", "TICK", ("M5", "M1", "TICK"), "starter_ticks@v0"),
    VirtualAccountSpec("highrisk_m1", "High-risk M1 growth experiment", 100.0, ACTIVE_DEMO, "highrisk", "M1", ("M15", "M5", "M1"), "highrisk_m1@v0"),
    VirtualAccountSpec("highrisk_ticks", "High-risk tick growth experiment", 100.0, ACTIVE_DEMO, "highrisk", "TICK", ("M5", "M1", "TICK"), "highrisk_ticks@v0"),
    VirtualAccountSpec("quota_30m_forward", "30-minute forced-quota forward research", 100.0, ACTIVE_DEMO, "quota_forward", "TICK", ("TICK",), "quota_30m@v0"),
    VirtualAccountSpec("quota_h1_forward", "Hourly forced-quota forward research", 100.0, ACTIVE_DEMO, "quota_forward", "M1", ("M1",), "quota_h1@v0"),
    VirtualAccountSpec("quota_h4_forward", "Four-hour quota execution research", 100.0, ACTIVE_DEMO, "quota_forward", "H4", ("H4",), "quota_h4_forward@execution_v1"),
    VirtualAccountSpec("quota_d1_forward", "Daily quota execution research", 100.0, ACTIVE_DEMO, "quota_forward", "D1", ("D1",), "quota_d1_forward@execution_v1"),
    # Phase-1 controlled experiment expansion. Most new accounts are PAPER/SHADOW
    # so they collect attributable counterfactual evidence without multiplying broker exposure.
    VirtualAccountSpec("iso_trend_h1", "Isolated trend H1", 100.0, PAPER, "isolated", "H1", ("H4","H1"), "ema_crossover@v1"),
    VirtualAccountSpec("iso_trend_m15", "Isolated trend M15", 100.0, PAPER, "isolated", "M15", ("H1","M15"), "ema_crossover@v1"),
    VirtualAccountSpec("iso_trend_m5", "Isolated trend M5", 100.0, PAPER, "isolated", "M5", ("M15","M5"), "ema_crossover@v1"),
    VirtualAccountSpec("iso_breakout_m15", "Isolated breakout M15", 100.0, PAPER, "isolated", "M15", ("H1","M15"), "donchian_breakout@v2"),
    VirtualAccountSpec("iso_breakout_m5", "Isolated breakout M5", 100.0, PAPER, "isolated", "M5", ("M15","M5"), "donchian_breakout@v2"),
    VirtualAccountSpec("iso_breakout_m1", "Isolated breakout M1", 100.0, SHADOW, "isolated", "M1", ("M5","M1"), "donchian_breakout@v2"),
    VirtualAccountSpec("iso_meanrev_m15", "Isolated mean reversion M15", 100.0, PAPER, "isolated", "M15", ("H1","M15"), "mean_reversion@v1"),
    VirtualAccountSpec("iso_meanrev_m5", "Isolated mean reversion M5", 100.0, PAPER, "isolated", "M5", ("M15","M5"), "mean_reversion@v1"),
    VirtualAccountSpec("iso_meanrev_m1", "Isolated mean reversion M1", 100.0, SHADOW, "isolated", "M1", ("M5","M1"), "mean_reversion@v1"),
    VirtualAccountSpec("iso_momentum_m15", "Isolated momentum M15", 100.0, SHADOW, "isolated", "M15", ("H1","M15"), "momentum_research@v0"),
    VirtualAccountSpec("iso_momentum_m5", "Isolated momentum M5", 100.0, SHADOW, "isolated", "M5", ("M15","M5"), "momentum_research@v0"),
    VirtualAccountSpec("iso_momentum_m1", "Isolated momentum M1", 100.0, SHADOW, "isolated", "M1", ("M5","M1"), "momentum_research@v0"),
    VirtualAccountSpec("family_trend_alltf", "Trend family all timeframes", 100.0, SHADOW, "strategy_family", "MULTI", ("H1","M15","M5","M1"), "family_trend@v0"),
    VirtualAccountSpec("family_breakout_alltf", "Breakout family all timeframes", 100.0, SHADOW, "strategy_family", "MULTI", ("H1","M15","M5","M1"), "family_breakout@v0"),
    VirtualAccountSpec("family_momentum_alltf", "Momentum family all timeframes", 100.0, SHADOW, "strategy_family", "MULTI", ("M15","M5","M1","TICK"), "family_momentum@v0"),
    VirtualAccountSpec("family_meanrev_alltf", "Mean reversion family all timeframes", 100.0, SHADOW, "strategy_family", "MULTI", ("M15","M5","M1","TICK"), "family_meanrev@v0"),
    VirtualAccountSpec("hybrid_balanced", "Hybrid balanced multi-strategy", 100.0, PAPER, "hybrid", "MULTI", ("H1","M15","M5","M1","TICK"), "hybrid_balanced@v0"),
    VirtualAccountSpec("hybrid_adaptive", "Hybrid regime-adaptive", 100.0, PAPER, "hybrid", "MULTI", ("H1","M15","M5","M1","TICK"), "hybrid_adaptive@v0"),
    VirtualAccountSpec("hybrid_aggressive", "Hybrid aggressive research", 100.0, PAPER, "hybrid", "MULTI", ("M15","M5","M1","TICK"), "hybrid_aggressive@v0"),
    VirtualAccountSpec("main_control", "Main control benchmark", 100.0, PAPER, "main", "MULTI", ("H4","H1","M15","M5","M1"), "main_control@v0"),
    VirtualAccountSpec("main_balanced", "Main balanced champion", 100.0, PAPER, "main", "MULTI", ("H4","H1","M15","M5","M1"), "main_balanced@v0"),
    VirtualAccountSpec("main_adaptive", "Main adaptive champion", 100.0, PAPER, "main", "MULTI", ("H4","H1","M15","M5","M1","TICK"), "main_adaptive@v0"),
    VirtualAccountSpec("main_challenger", "Main challenger", 100.0, PAPER, "main", "MULTI", ("H4","H1","M15","M5","M1"), "main_challenger@v0"),
    VirtualAccountSpec("hr20_trend", "20pct risk trend lab", 100.0, PAPER, "ultra_highrisk", "MULTI", ("M15","M5","M1"), "hr20_trend@v0"),
    VirtualAccountSpec("hr20_momentum", "20pct risk momentum lab", 100.0, PAPER, "ultra_highrisk", "MULTI", ("M15","M5","M1","TICK"), "hr20_momentum@v0"),
    VirtualAccountSpec("hr20_breakout", "20pct risk breakout lab", 100.0, PAPER, "ultra_highrisk", "MULTI", ("M15","M5","M1"), "hr20_breakout@v0"),
    VirtualAccountSpec("hr20_meanrev", "20pct risk mean-reversion lab", 100.0, PAPER, "ultra_highrisk", "MULTI", ("M15","M5","M1"), "hr20_meanrev@v0"),
    VirtualAccountSpec("news_breakout", "News event breakout lab", 100.0, SHADOW, "news", "EVENT", ("M15","M5","M1"), "news_breakout@v0"),
    VirtualAccountSpec("news_momentum", "News event momentum lab", 100.0, SHADOW, "news", "EVENT", ("M15","M5","M1"), "news_momentum@v0"),
    VirtualAccountSpec("news_control", "News no-entry counterfactual control", 100.0, SHADOW, "news", "EVENT", ("M15","M5","M1"), "news_control@v0"),
)


def ensure_virtual_accounts() -> dict:
    """Seeds missing lab accounts without overwriting accumulated results."""
    state = load_state()
    accounts = dict(state.get("virtual_accounts") or {})
    changed = False
    for spec in DEFAULT_VIRTUAL_ACCOUNTS:
        spec_row = asdict(spec)
        spec_row["context_timeframes"] = list(spec.context_timeframes)
        if spec.account_id in accounts:
            # Keep accumulated P&L/statistics, but reconcile descriptive
            # metadata/execution tier with the current lab configuration.
            row = dict(accounts[spec.account_id])
            for key in (
                "label", "starting_equity", "execution_tier", "horizon",
                "entry_timeframe", "context_timeframes", "strategy_tag",
            ):
                if row.get(key) != spec_row.get(key):
                    row[key] = spec_row.get(key)
                    changed = True
            accounts[spec.account_id] = row
            continue
        row = spec_row
        row.update({
            "equity": spec.starting_equity,
            "high_water_mark": spec.starting_equity,
            "realized_pnl": 0.0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
        })
        accounts[spec.account_id] = row
        changed = True
    if changed:
        set_virtual_accounts(accounts)
    return accounts


def account_for_strategy(strategy_tag: str) -> Optional[str]:
    for spec in DEFAULT_VIRTUAL_ACCOUNTS:
        if spec.strategy_tag == strategy_tag:
            return spec.account_id
    return None


def _apply_close_to_row(row: dict, account_id: str, pnl: float) -> dict:
    """Pure P&L application to one already-loaded account row -- no I/O of
    its own, so a caller that needs this bundled atomically with OTHER
    state mutations (trade_settlements' dedup outbox and open_trades'
    pop, see commit_trade_settlement below) can do so in one load/write,
    while record_virtual_close (an existing, simpler caller that doesn't
    need that) still gets identical accounting."""
    row = dict(row)
    row["realized_pnl"] = round(float(row.get("realized_pnl", 0.0)) + pnl, 2)
    row["equity"] = round(float(row.get("equity", row["starting_equity"])) + pnl, 2)
    row["high_water_mark"] = max(float(row.get("high_water_mark", row["starting_equity"])), row["equity"])
    row["closed_trades"] = int(row.get("closed_trades", 0)) + 1
    if pnl > 0:
        row["wins"] = int(row.get("wins", 0)) + 1
    elif pnl < 0:
        row["losses"] = int(row.get("losses", 0)) + 1
    # Research "ruin" event: keep the ledger alive for analysis but mark
    # catastrophic drawdowns so we can study why aggressive variants failed.
    start = float(row.get("starting_equity", 100.0))
    dd = 0.0 if start <= 0 else max(0.0, (start - float(row["equity"])) / start)
    row["drawdown_from_start_pct"] = round(dd * 100.0, 2)
    ruined_now = float(row["equity"]) <= start * 0.25
    if ruined_now and not row.get("ruined"):
        row["ruined"] = True
        row["ruined_at"] = datetime.now(timezone.utc).isoformat()
        RUIN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with RUIN_LOG_PATH.open("a") as f:
            f.write(json.dumps({
                "timestamp": row["ruined_at"],
                "virtual_account_id": account_id,
                "strategy": row.get("strategy_tag"),
                "starting_equity": start,
                "equity": row["equity"],
                "realized_pnl": row.get("realized_pnl", 0.0),
                "closed_trades": row.get("closed_trades", 0),
                "wins": row.get("wins", 0),
                "losses": row.get("losses", 0),
                "drawdown_from_start_pct": row["drawdown_from_start_pct"],
                "reason": "virtual account equity fell to <=25% of starting equity"
            }) + "\n")
    return row


def record_virtual_close(account_id: str, pnl: float) -> dict:
    """Apply an attributable closed-trade P&L to one logical $100 ledger."""
    accounts = ensure_virtual_accounts()
    if account_id not in accounts:
        raise KeyError(f"Unknown virtual account: {account_id}")
    row = _apply_close_to_row(accounts[account_id], account_id, pnl)
    accounts[account_id] = row
    set_virtual_accounts(accounts)
    return row


def flush_trade_settlements() -> None:
    """Replay trade_settlements' outbox into the Trade Database without
    ever re-touching equity -- same replay-without-double-credit shape as
    quota.py's own flush_settlements, generalized so every close path can
    share it. Safe to call any time (e.g. speculatively, at the start of
    a run) since it's a no-op for any contract_id already in the log."""
    known = {int(r["contract_id"]) for r in load_trades()}
    for cid, row in _state.load_state().get("trade_settlements", {}).items():
        if int(cid) not in known:
            record_trade(TradeRecord(**row))
            known.add(int(cid))


def commit_trade_settlement(record: TradeRecord) -> Optional[dict]:
    """Atomically settles one closed contract: applies its P&L to the
    owning virtual account (if any), queues it for the Trade Database, and
    removes it from open_trades tracking -- as ONE state write, keyed by
    contract_id, so a retry after a partial failure can never double-apply
    the same contract's P&L.

    This generalizes quota.py's own commit_close/flush_settlements
    pattern (the one place in this codebase that already got this right)
    to every other close path. Before this existed, scheduler.py's two
    close paths and champion_scheduler.py's own each called
    record_virtual_close() and record_trade() as separate, non-atomic
    steps ("pop_open_trade last" only prevented losing track of a contract
    on failure -- it did NOT prevent double-applying its P&L if
    record_virtual_close succeeded but record_trade then raised: the
    contract stayed in open_trades, un-popped, so the NEXT run's retry
    walked through record_virtual_close again for the exact same pnl).
    Confirmed reproducible: a single $4.50 win applied twice took a $100
    account to $109.

    Returns the updated virtual account row (or None if this record has no
    virtual_account_id -- nothing to apply, but the settlement + open_trades
    pop still happen), or None without any mutation at all if this exact
    contract_id was already settled by an earlier, successful call (verified
    against the outbox for a conflicting pnl/account, which raises instead
    of silently accepting different evidence for the same contract).

    The Trade Database append itself (flush_trade_settlements, a separate
    file from the state this function's own write is atomic against) is
    attempted opportunistically before returning, but a failure there is
    swallowed (logged, not raised): by that point the equity mutation and
    dedup outbox entry are already durably committed, so there is nothing
    left to roll back, and nothing would be gained by making this call
    (or its caller, e.g. mid-run in scheduler.py) fail over a lagging log
    line that a later flush_trade_settlements() call -- explicit, or the
    next run's own speculative one -- will pick up and complete without
    ever re-touching equity."""
    s = _state.load_state()
    key = str(record.contract_id)
    outbox = s.setdefault("trade_settlements", {})
    if key in outbox:
        prior = outbox[key]
        if prior["pnl"] != record.pnl or prior.get("virtual_account_id") != record.virtual_account_id:
            raise RuntimeError(
                f"Conflicting settlement evidence for contract {record.contract_id}: "
                f"already settled as pnl={prior['pnl']} account={prior.get('virtual_account_id')!r}, "
                f"now given pnl={record.pnl} account={record.virtual_account_id!r}"
            )
        _try_flush_trade_settlements()
        return None
    row = None
    if record.virtual_account_id and record.pnl is not None:
        # pnl is None for a real exit whose P&L simply isn't attributable
        # (see TradeRecord.pnl's own docstring) -- never coerced to 0.0,
        # which would silently apply a fabricated break-even close.
        accounts = dict(s.get("virtual_accounts") or {})
        if record.virtual_account_id not in accounts:
            raise KeyError(f"Unknown virtual account: {record.virtual_account_id}")
        row = _apply_close_to_row(accounts[record.virtual_account_id], record.virtual_account_id, record.pnl)
        accounts[record.virtual_account_id] = row
        s["virtual_accounts"] = accounts
        # Deliberately NOT setting record.equity_after here: it already
        # means different things to different callers (this isolated sub-
        # account's own equity for quota.py's callers; the shared CORE
        # account's overall equity snapshot for scheduler.py's) -- the
        # caller sets whichever is correct for it before calling this.
    outbox[key] = asdict(record)
    s.setdefault("open_trades", {}).pop(key, None)
    _state._write_state(s)
    _try_flush_trade_settlements()
    return row


def _try_flush_trade_settlements() -> None:
    try:
        flush_trade_settlements()
    except Exception:
        logger.warning(
            "flush_trade_settlements failed after a settlement was already durably committed to state -- "
            "the Trade Database append will be retried by a later flush_trade_settlements() call "
            "(explicit, or the next run's own speculative one). Equity was NOT affected.",
            exc_info=True,
        )

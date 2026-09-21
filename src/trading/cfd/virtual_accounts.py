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

from trading.cfd.state import load_state, set_virtual_accounts


ACTIVE_DEMO = "ACTIVE_DEMO"
PAPER = "PAPER"
SHADOW = "SHADOW"


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
    VirtualAccountSpec("breakout_h1", "H1 breakout forward lab", 100.0, PAPER, "swing", "H1", ("H4", "H1"), "donchian_breakout@v2"),
    VirtualAccountSpec("intraday_m15", "M15 intraday research", 100.0, SHADOW, "intraday", "M15", ("H4", "H1", "M15")),
    VirtualAccountSpec("intraday_m5", "M5 intraday research", 100.0, SHADOW, "intraday", "M5", ("H1", "M15", "M5")),
    VirtualAccountSpec("starter_m5_probe", "M5 starter demo probe", 100.0, ACTIVE_DEMO, "intraday", "M5", ("H1", "M15", "M5"), "starter_intraday@v0"),
    VirtualAccountSpec("scalp_m1", "M1 execution research", 100.0, ACTIVE_DEMO, "scalp", "M1", ("M15", "M5", "M1"), "starter_m1@v0"),
    VirtualAccountSpec("scalp_ticks", "Tick-seconds execution research", 100.0, ACTIVE_DEMO, "scalp", "TICK", ("M5", "M1", "TICK"), "starter_ticks@v0"),
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


def record_virtual_close(account_id: str, pnl: float) -> dict:
    """Apply an attributable closed-trade P&L to one logical $100 ledger."""
    accounts = ensure_virtual_accounts()
    if account_id not in accounts:
        raise KeyError(f"Unknown virtual account: {account_id}")
    row = dict(accounts[account_id])
    row["realized_pnl"] = round(float(row.get("realized_pnl", 0.0)) + pnl, 2)
    row["equity"] = round(float(row.get("equity", row["starting_equity"])) + pnl, 2)
    row["high_water_mark"] = max(float(row.get("high_water_mark", row["starting_equity"])), row["equity"])
    row["closed_trades"] = int(row.get("closed_trades", 0)) + 1
    if pnl > 0:
        row["wins"] = int(row.get("wins", 0)) + 1
    elif pnl < 0:
        row["losses"] = int(row.get("losses", 0)) + 1
    accounts[account_id] = row
    set_virtual_accounts(accounts)
    return row

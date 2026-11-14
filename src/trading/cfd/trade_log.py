"""Trade Database -- src/trading/cfd/trade_log.py

An append-only log of closed CFD trades, the "Trade Database" stage of
docs/VISION.md's pipeline. trading.cfd.performance reads it to compute
real performance metrics; a future Failure Analysis / Research Lab stage
(see docs/ARCHITECTURE_AUDIT.md's phase 2+) will read it too, once it
exists, instead of guessing from theory.

Stored as JSON Lines (one JSON object per line), not a single JSON array,
so a crash mid-write can never corrupt previously-recorded trades --
appending one line is effectively atomic at the write volume this system
produces (at most a few trades per hour).

All money fields (stake, risk_amount, pnl, equity_before, equity_after)
are in *virtual* equity terms for a demo account -- see
trading.cfd.capital -- so they're directly comparable to
CFD_VIRTUAL_STARTING_CAPITAL, not the raw ~$10,000 Deriv demo balance.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

_LOG_PATH = Path(__file__).resolve().parents[3] / "state" / "cfd_trades.jsonl"


@dataclass
class TradeRecord:
    contract_id: int
    instrument: str
    strategy: str
    side: str
    entry_time: str
    exit_time: str
    entry_price: float
    stake: float
    risk_amount: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    """None means the exit was real but its P&L wasn't attributable --
    e.g. more than one tracked contract disappeared (closed externally by
    Deriv's own stop-loss/take-profit) in the same run, with no way to
    split one combined balance change between them. See
    scheduler.py's reconciliation logic. Never coerced to 0.0 -- that
    would silently bias every performance average toward zero for
    trades that just haven't been priced yet."""
    equity_before: Optional[float] = None
    equity_after: Optional[float] = None
    exit_reason: str = ""
    regime: Optional[str] = None
    """The trading.cfd.regime classification (e.g. "trending") in effect
    when this trade was opened -- set by scheduler.py from the same
    regime the Strategy Selector used to pick this trade's strategy."""
    thesis_key: Optional[str] = None
    """trading.cfd.portfolio_risk.thesis_key(instrument, side) -- which
    risk bucket this trade counted against for the per-thesis ceiling at
    entry time, tagged here (not just recomputed later) so the audit
    trail survives even if the thesis-grouping rule itself changes in a
    future revision. None only for a trade logged before this field
    existed."""
    leg: Optional[str] = None
    virtual_account_id: Optional[str] = None
    """Logical $100 sub-account that owns this trade. None for legacy
    records created before the virtual-account laboratory existed."""
    horizon: Optional[str] = None
    """core/swing/intraday/scalp -- recorded at entry for later cohort analysis."""
    entry_timeframe: Optional[str] = None
    """Execution timeframe, e.g. H1, M15, M5, M1."""
    context_timeframes: Optional[list[str]] = None
    """Higher/lower timeframes used as context when the trade was opened."""
    """"scalp" or "runner" -- see trading.cfd.exit_manager.
    split_stake_for_partial_close. A "scalp" leg keeps the strategy's own
    normal fixed target; a "runner" leg has no effective fixed target and
    is managed by the trailing stop instead. None for a trade logged
    before Adaptive Exit Management existed, or for a runner-only entry
    that never actually split (still tagged "runner", just at full
    size -- see split_stake_for_partial_close's docstring for why)."""


def record_trade(trade: TradeRecord, path: Optional[Path] = None) -> None:
    """path defaults to the real Trade Database (_LOG_PATH) -- pass a
    different path to log elsewhere, e.g. trading.cfd.paper_trading's
    separate paper-trade log, so paper and real P&L are never mixed in
    the same file."""
    p = path or _LOG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(asdict(trade)) + "\n")


def load_trades(path: Optional[Path] = None) -> list[dict]:
    p = path or _LOG_PATH
    if not p.exists():
        return []
    trades = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            trades.append(json.loads(line))
    return trades

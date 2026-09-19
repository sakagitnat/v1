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
    """Not populated yet -- no CFD Market Regime Engine exists as of this
    writing (see docs/ARCHITECTURE_AUDIT.md). Present now so
    performance.py's by-regime breakdown and the trade schema don't need
    to change again once one does."""


def record_trade(trade: TradeRecord) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a") as f:
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

"""Portfolio Risk Governor -- src/trading/cfd/portfolio_risk.py

Closes Revision 3 gap #2 (docs/ARCHITECTURE_AUDIT.md): before this
module, the only risk ceilings that existed were per-position
(`CfdRiskManager.risk_per_trade`, `CFD_MAX_RISK_PER_TRADE_CEILING`) and a
raw position-*count* cap (`max_open_positions`) -- nothing capped
aggregate dollar risk across several simultaneously open positions,
nothing recognized that several positions can be the same underlying bet
(a "thesis") or correlated bets expressed through different instruments,
and nothing could reject a new position purely because the PORTFOLIO,
not any one position, was already at its risk limit. Per
docs/VISION.md's "Risk model" section, this is the part of the Hard Risk
Governor that sits above per-position sizing -- deliberately **not**
satisfiable by counting positions, only by summing actual risk dollars
(and notional exposure, for the leverage ceiling).

Every check here can only ever REJECT an otherwise-valid new entry
(SKIP TRADE, same semantics as every other hard risk check in this
codebase -- see risk.py's min-stake-skip and daily-loss-halt) -- it never
silently shrinks a position to fit. A rejected entry is logged and
explained, never silent.

Thesis: two positions are "the same underlying bet" if they're the same
instrument and the same side (long/short) -- e.g. five long orders on
frxXAUUSD is one thesis, not five independent opportunities, exactly the
disguised-risk-split docs/VISION.md forbids. (The broker layer already
allows at most one open position per instrument -- see broker.py's
open_positions() docstring -- so today a same-instrument thesis can
never literally stack more than one live position; this ceiling is the
explicit, audited version of that constraint, and stays correct if that
broker-side limitation is ever lifted.)

Correlation: a STATIC, CONFIGURED factor map (CORRELATION_FACTORS below),
not a computed rolling correlation -- this project has no market-data
infrastructure for the latter yet, and a static map is an honest,
auditable starting point rather than pretending to more precision than
exists. Every one of today's four configured instruments is USD-exposed
(gold and EUR/GBP move opposite USD; USDJPY has USD as the base currency,
so it moves the SAME direction as USD, not the opposite) -- see
CORRELATION_FACTORS's signs below. Two open positions correlate on a
factor only when their *signed* exposure to it has the same sign (both
effectively betting USD weakens, say) -- an opposite-signed pair on the
same factor is a natural hedge, tracked separately, and never inflates
the correlated-risk figure.
"""
from dataclasses import dataclass
from typing import Optional

CORRELATION_FACTORS: dict[str, dict[str, float]] = {
    "frxXAUUSD": {"usd": -1.0},  # gold up when USD weakens
    "frxEURUSD": {"usd": -1.0},  # EUR up (quote is USD per EUR) when USD weakens
    "frxGBPUSD": {"usd": -1.0},  # same shape as EURUSD
    "frxUSDJPY": {"usd": 1.0},   # USD is the BASE currency here -- pair rises WITH USD
}
"""instrument -> {factor_name: sign}. An instrument not listed here has no
factor exposure (empty dict) -- it still counts fully toward its own
thesis ceiling and the total portfolio ceiling, it just never groups with
anything else via the correlated-risk ceiling. Extend this, not the
checking logic below, when a new instrument or factor is added."""


def thesis_key(instrument: str, side: str) -> str:
    """The bucket two positions must share to be "the same underlying
    bet" -- same instrument, same side. See this module's docstring."""
    return f"{instrument}:{side}"


def factor_exposures(instrument: str, side: str) -> dict[str, float]:
    """Signed exposure to each correlation factor for a position on
    `instrument`/`side` -- short flips every sign from CORRELATION_FACTORS
    (a short bet is the opposite direction on every factor a long bet
    would carry)."""
    base = CORRELATION_FACTORS.get(instrument, {})
    sign = 1.0 if side == "long" else -1.0
    return {factor: weight * sign for factor, weight in base.items()}


@dataclass
class OpenRiskPosition:
    """The minimum a currently-open position must carry for portfolio
    risk aggregation -- built from trading.cfd.state.list_open_trades()'s
    persisted metadata (see scheduler.py), so this reflects positions
    open from EARLIER runs too, not just ones opened this run."""

    contract_id: int
    instrument: str
    side: str
    risk_amount: float
    notional: float = 0.0
    """stake * multiplier -- 0.0 for a position recorded before this
    field existed (backward compatible: such a position still counts
    fully toward every risk-dollar ceiling, just not the leverage one)."""


@dataclass
class PortfolioRiskCeilings:
    max_thesis_risk_pct: float
    max_correlated_risk_pct: float
    max_portfolio_risk_pct: float
    max_exposure_multiple: float


def factor_group_totals(open_positions: list[OpenRiskPosition]) -> dict[str, float]:
    """{"factor:long"|"factor:short" -> summed risk_amount} -- grouped by
    the SIGN of each position's exposure to that factor, so a natural
    hedge (opposite-signed exposure to the same factor) is tracked in a
    separate group and never inflates the correlated-risk figure."""
    totals: dict[str, float] = {}
    for pos in open_positions:
        for factor, signed in factor_exposures(pos.instrument, pos.side).items():
            group = f"{factor}:{'long' if signed > 0 else 'short'}"
            totals[group] = totals.get(group, 0.0) + pos.risk_amount
    return totals


def check_new_position(
    open_positions: list[OpenRiskPosition],
    new_instrument: str,
    new_side: str,
    new_risk_amount: float,
    new_notional: float,
    equity: float,
    ceilings: PortfolioRiskCeilings,
) -> Optional[str]:
    """Returns None if the new position is allowed, or a human-readable
    rejection reason if it would breach any ceiling -- the caller's job is
    to SKIP TRADE on a non-None result, exactly like every other hard risk
    check in this codebase. Checks, in order: per-thesis, correlated,
    total portfolio, then leverage/exposure -- the first breach found is
    the one reported, so a caller never has to guess which ceiling was
    binding."""
    if equity <= 0:
        return "equity is zero or negative -- no new position can be sized"

    key = thesis_key(new_instrument, new_side)
    thesis_total = new_risk_amount + sum(
        p.risk_amount for p in open_positions if thesis_key(p.instrument, p.side) == key
    )
    thesis_pct = thesis_total / equity
    if thesis_pct > ceilings.max_thesis_risk_pct:
        return (
            f"thesis {key!r} risk would reach {thesis_pct:.2%} of equity, "
            f"over the {ceilings.max_thesis_risk_pct:.2%} per-thesis ceiling"
        )

    new_factors = factor_exposures(new_instrument, new_side)
    if new_factors:
        existing_factor_totals = factor_group_totals(open_positions)
        for factor, signed in new_factors.items():
            group = f"{factor}:{'long' if signed > 0 else 'short'}"
            correlated_total = new_risk_amount + existing_factor_totals.get(group, 0.0)
            correlated_pct = correlated_total / equity
            if correlated_pct > ceilings.max_correlated_risk_pct:
                return (
                    f"correlated risk on {group!r} would reach {correlated_pct:.2%} of equity, "
                    f"over the {ceilings.max_correlated_risk_pct:.2%} correlated-risk ceiling"
                )

    portfolio_total = new_risk_amount + sum(p.risk_amount for p in open_positions)
    portfolio_pct = portfolio_total / equity
    if portfolio_pct > ceilings.max_portfolio_risk_pct:
        return (
            f"total portfolio risk would reach {portfolio_pct:.2%} of equity, "
            f"over the {ceilings.max_portfolio_risk_pct:.2%} portfolio risk ceiling"
        )

    total_notional = new_notional + sum(p.notional for p in open_positions)
    exposure_multiple = total_notional / equity
    if exposure_multiple > ceilings.max_exposure_multiple:
        return (
            f"total notional exposure would reach {exposure_multiple:.2f}x equity, "
            f"over the {ceilings.max_exposure_multiple:.2f}x leverage/exposure ceiling"
        )

    return None

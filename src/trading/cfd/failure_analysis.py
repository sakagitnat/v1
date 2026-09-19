"""Failure Analysis -- src/trading/cfd/failure_analysis.py

Classifies why a closed trade lost money, from docs/VISION.md's Failure
Analysis section, and separately flags when a strategy's *recent*
performance looks meaningfully worse than its own history (strategy
degradation) -- both read straight from the Trade Database
(trading.cfd.trade_log), the same offline, no-API-call shape as
trading.cfd.performance.

Only classifies what's honestly inferable from what a TradeRecord
actually stores. Several of the vision's categories need data this
project doesn't capture yet, and are never guessed at:
  - "abnormal market/news event" needs a news feed
  - "execution problem" needs order latency/fill-quality data
  - "data problem" needs data-quality/integrity checks on the candles used
  - "spread/slippage problem" isn't separable from a stop-out simply
    costing more than intended (both would show up as the same
    "excessive_risk" signal below) without price-level data this
    project's TradeRecord doesn't keep (only the dollar risk_amount, not
    the stop/target price levels themselves)
None of those are ever returned here -- a loss that might fall into one
of them is classified "normal_statistical_loss" (the honest default) or
"unattributed" (no pnl yet), never a fabricated specific cause. See
docs/ARCHITECTURE_AUDIT.md for these as open gaps, not silently assumed
away.

This module only reports. It never writes to the Strategy Registry --
detect_degradation() flags a strategy for a human to look at and decide
via `cfd_cli.py promote-strategy ... PAUSED`, exactly the same deliberate,
audited, manual promotion path every other lifecycle change goes
through (see trading.cfd.strategy_registry). Acting on this
automatically would be the kind of "AI overrides the Risk Governor /
hot-edits a live strategy without validation" docs/VISION.md forbids.
"""
from typing import Optional

from trading.cfd.strategy_registry import get

EXCESSIVE_RISK_R_MULTIPLE = -1.5
"""A loss worse than 1.5x the trade's budgeted risk_amount (R multiple
<= -1.5) signals the stop didn't cap the loss the way it was sized to --
a gap, slippage, or a sizing bug, not the ordinary "lost the budgeted
risk_amount and no more" outcome a strategy's edge already accounts for.
Not walked through a TRAIN/TEST split (there's no historical loss-cause
ground truth to validate against) -- a reasoned, documented default, not
yet a validated one, same caveat as trading.cfd.regime's trend_threshold."""

DEGRADATION_DROP_FRACTION = 0.5
"""A strategy is flagged degraded if its most recent window's expectancy
per trade has fallen by at least this fraction versus its own prior
history (or turned zero-or-negative when prior history was positive).
50% is a deliberately conservative bar -- flag real decay, not normal
variance around a middling edge. Not yet validated against real
degradation episodes (none have happened yet); revisit once some have."""


def classify_loss(trade: dict) -> str:
    """Classifies one trade dict (as trading.cfd.trade_log.load_trades()
    returns) into: "not_a_loss" (pnl >= 0), "unattributed" (pnl is None --
    see trading.cfd.trade_log.TradeRecord.pnl's docstring),
    "regime_mismatch" (the regime recorded at entry wasn't in the
    strategy's suited_regimes -- only possible for a trade logged before
    trading.cfd.selector's regime gate existed, or with a stale/renamed
    registry entry), "excessive_risk" (see EXCESSIVE_RISK_R_MULTIPLE), or
    the default "normal_statistical_loss" -- a loss consistent with the
    strategy's own budgeted risk, exactly the kind of loss a real edge is
    expected to take some of the time."""
    pnl = trade.get("pnl")
    if pnl is None:
        return "unattributed"
    if pnl >= 0:
        return "not_a_loss"

    regime = trade.get("regime")
    strategy_tag = trade.get("strategy") or ""
    name, _, version = strategy_tag.partition("@")
    entry = get(name, version) if name and version else None
    if entry is not None and regime and entry.suited_regimes and regime not in entry.suited_regimes:
        return "regime_mismatch"

    risk_amount = trade.get("risk_amount")
    r_multiple = pnl / risk_amount if risk_amount else None
    if r_multiple is not None and r_multiple <= EXCESSIVE_RISK_R_MULTIPLE:
        return "excessive_risk"

    return "normal_statistical_loss"


def summarize_losses(trades: list[dict]) -> dict:
    """Buckets every losing trade by classify_loss(), with count, total
    pnl, and the contract_ids in each bucket -- an at-a-glance answer to
    "what's actually costing money, and is it the ordinary cost of the
    edge or something else.\""""
    losses = [t for t in trades if t.get("pnl") is not None and t["pnl"] < 0]
    summary: dict[str, dict] = {}
    for t in losses:
        category = classify_loss(t)
        bucket = summary.setdefault(category, {"count": 0, "total_pnl": 0.0, "contract_ids": []})
        bucket["count"] += 1
        bucket["total_pnl"] = round(bucket["total_pnl"] + t["pnl"], 2)
        bucket["contract_ids"].append(t.get("contract_id"))
    return summary


def detect_degradation(trades: list[dict], strategy_tag: str, recent_window: int = 10) -> Optional[dict]:
    """Compares a strategy's most recent recent_window priced trades'
    expectancy against its own prior history's expectancy (excluding that
    recent window, so the comparison is against genuinely earlier trades,
    not a window that includes itself).

    Returns None if there aren't at least recent_window*2 priced trades
    for this strategy yet -- too little history to tell real decay from
    ordinary variance. Otherwise returns a dict with "degraded": bool and
    the numbers behind that call, for a human to act on (see this
    module's docstring -- never auto-applied)."""
    own_trades = sorted(
        (t for t in trades if t.get("strategy") == strategy_tag and t.get("pnl") is not None),
        key=lambda t: t["exit_time"],
    )
    if len(own_trades) < recent_window * 2:
        return None

    recent = own_trades[-recent_window:]
    prior = own_trades[:-recent_window]
    recent_expectancy = sum(t["pnl"] for t in recent) / len(recent)
    prior_expectancy = sum(t["pnl"] for t in prior) / len(prior)

    degraded = False
    reason = "no significant change"
    if prior_expectancy > 0 and recent_expectancy <= 0:
        degraded = True
        reason = f"expectancy went from positive ({prior_expectancy:.2f}) to zero-or-negative ({recent_expectancy:.2f})"
    elif prior_expectancy > 0 and recent_expectancy < prior_expectancy * (1 - DEGRADATION_DROP_FRACTION):
        drop_pct = (prior_expectancy - recent_expectancy) / prior_expectancy * 100
        degraded = True
        reason = f"expectancy dropped {drop_pct:.0f}% vs. prior history ({prior_expectancy:.2f} -> {recent_expectancy:.2f})"

    return {
        "strategy": strategy_tag,
        "degraded": degraded,
        "reason": reason,
        "recent_expectancy": round(recent_expectancy, 2),
        "prior_expectancy": round(prior_expectancy, 2),
        "recent_window": recent_window,
        "prior_trade_count": len(prior),
    }

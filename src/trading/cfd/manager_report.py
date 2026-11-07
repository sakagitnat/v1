"""AI Trading Manager -- Management Report -- src/trading/cfd/manager_report.py

Ties together everything built so far (Trade Database, Performance
Engine, Failure Analysis, Strategy Registry, Portfolio Allocator,
Portfolio Risk Governor, Drawdown Monitor, Research Lab, Paper Trading)
into one consolidated report: what's actually happening across every
registered strategy, and what still needs a human's attention.
allocation_summary, portfolio_risk_summary, and drawdown_summary in the
returned dict are purely informational, same as degradation: the live
scheduler already applies trading.cfd.portfolio_allocator's weights,
trading.cfd.portfolio_risk's ceilings, and trading.cfd.drawdown_monitor's
tier every run, this just makes the current numbers visible. Every
equity figure here is an offline approximation (starting_equity +
realized net_return) except drawdown_summary's high_water_mark, which is
exact (updated from real broker equity on every live run) -- this report
never connects to Deriv, so it can't see live broker equity or
unrealized P&L itself.

This module itself NEVER takes action -- it only reports, in the form of
the exact `cfd_cli.py` command that would carry out each suggestion (or,
for degradation, what trading.cfd.decay_supervisor already did
automatically on the live scheduler's last run -- see below). Every
recommendation this module surfaces that would RAISE risk or cross a
boundary (promoting VALIDATED->PAPER, PAPER->ACTIVE) still needs a human
to run the command themselves, per docs/VISION.md's "Autonomy
boundaries": those directions always need explicit approval. Actions
that only ever LOWER risk (demoting a decaying ACTIVE strategy) don't
wait for this report at all -- trading.cfd.decay_supervisor.
run_autonomous_demotion() already does those automatically, on the
regular scheduler run, before a human ever reads this report.

Non-degradation recommendations are deterministic and fully explained --
no black box: every one names the specific number(s) that triggered it.
"""
from dataclasses import dataclass
from typing import Optional

from trading.cfd.decision_log import load_decisions
from trading.cfd.incident_log import load_incidents
from trading.cfd.drawdown_monitor import DrawdownThresholds, classify_drawdown_tier, drawdown_risk_multiplier
from trading.cfd.failure_analysis import detect_degradation, summarize_losses
from trading.cfd.performance import compute_performance
from trading.cfd.portfolio_allocator import compute_allocations
from trading.cfd.portfolio_risk import OpenRiskPosition, factor_group_totals, thesis_key
from trading.cfd.state import get_equity_tracking, list_open_trades
from trading.cfd.strategy_registry import LifecycleState, list_all
from trading.config import settings


@dataclass
class Recommendation:
    type: str
    strategy: str
    reason: str
    command: str


def _degradation_recommendations(trades: list[dict], registry_entries: list) -> list[Recommendation]:
    """Surfaces any ACTIVE strategy that's currently degraded -- almost
    always informational, not an action request: trading.cfd.
    decay_supervisor.run_autonomous_demotion() already demotes these on
    the scheduler's very next run, no human required (docs/VISION.md's
    "Autonomy boundaries"). Seeing one listed here usually just means
    that run hasn't happened yet since the degradation appeared. The
    command is still given for a human who wants to act sooner than the
    next scheduled run, not because it's required."""
    recs = []
    for entry in registry_entries:
        if entry.state != LifecycleState.ACTIVE.value:
            continue
        tag = f"{entry.name}@{entry.version}"
        result = detect_degradation(trades, tag)
        if result and result["degraded"]:
            recs.append(
                Recommendation(
                    type="degrading_strategy_pending_autonomous_demotion",
                    strategy=tag,
                    reason=f"{result['reason']} -- will be auto-demoted to PAUSED on the next scheduler run if not already.",
                    command=f"cfd_cli.py promote-strategy {entry.name} {entry.version} PAUSED --reason \"degradation: {result['reason']}\" (optional -- happens automatically otherwise)",
                )
            )
    return recs


def _validated_awaiting_paper_recommendations(registry_entries: list) -> list[Recommendation]:
    recs = []
    for entry in registry_entries:
        if entry.state != LifecycleState.VALIDATED.value:
            continue
        tag = f"{entry.name}@{entry.version}"
        recs.append(
            Recommendation(
                type="advance_validated_to_paper",
                strategy=tag,
                reason="cleared automated validation (Backtest/TEST/Walk-Forward/Monte Carlo) -- next step is forward-looking paper trading, not a jump straight to real money.",
                command=f"cfd_cli.py promote-strategy {entry.name} {entry.version} PAPER --reason \"starting paper trading\"",
            )
        )
    return recs


def _paper_promotion_recommendations(paper_trades: list[dict], registry_entries: list, min_paper_trades: int = 20) -> list[Recommendation]:
    """A PAPER strategy with enough simulated trade history and a
    healthy expectancy is worth a human's look for promotion to ACTIVE --
    never automatic. min_paper_trades=20 is the same MIN_TRADES bar
    trading.cfd.research_lab uses for a backtest's TRAIN period; not
    independently validated for paper-trading sample size specifically."""
    recs = []
    for entry in registry_entries:
        if entry.state != LifecycleState.PAPER.value:
            continue
        tag = f"{entry.name}@{entry.version}"
        own = [t for t in paper_trades if t.get("strategy") == tag and t.get("pnl") is not None]
        if len(own) < min_paper_trades:
            continue
        perf = compute_performance(own, starting_equity=settings.cfd_virtual_starting_capital)
        if perf["expectancy"] > 0 and perf["win_rate_pct"] > 0:
            recs.append(
                Recommendation(
                    type="consider_promoting_paper_strategy",
                    strategy=tag,
                    reason=f"{len(own)} paper trades, expectancy {perf['expectancy']:+.2f}, win rate {perf['win_rate_pct']:.1f}% -- worth reviewing for ACTIVE.",
                    command=f"cfd_cli.py promote-strategy {entry.name} {entry.version} ACTIVE --reason \"paper trading results reviewed\"",
                )
            )
    return recs


def _portfolio_risk_summary(equity_estimate: float) -> dict:
    """Current utilization of every trading.cfd.portfolio_risk ceiling,
    purely informational (this report never rejects anything -- the live
    scheduler's own check_new_position() call already does that at entry
    time). equity_estimate is starting_equity + realized net_return -- an
    approximation, not live broker equity, since this report runs offline
    (no Deriv connection) and doesn't know about unrealized P&L on any
    currently open position."""
    open_trades = list_open_trades()
    positions = [
        OpenRiskPosition(
            contract_id=int(cid),
            instrument=meta.get("instrument", ""),
            side=meta.get("side", ""),
            risk_amount=meta.get("risk_amount", 0.0),
            notional=meta.get("stake", 0.0) * meta.get("multiplier", 0.0),
        )
        for cid, meta in open_trades.items()
    ]
    thesis_totals: dict[str, float] = {}
    for pos in positions:
        key = thesis_key(pos.instrument, pos.side)
        thesis_totals[key] = thesis_totals.get(key, 0.0) + pos.risk_amount

    return {
        "equity_basis": round(equity_estimate, 2),
        "equity_basis_note": "starting_equity + realized net_return -- offline approximation, not live broker equity",
        "open_position_count": len(positions),
        "thesis_risk": {k: round(v, 2) for k, v in thesis_totals.items()},
        "correlated_risk": {k: round(v, 2) for k, v in factor_group_totals(positions).items()},
        "total_portfolio_risk": round(sum(p.risk_amount for p in positions), 2),
        "total_notional_exposure": round(sum(p.notional for p in positions), 2),
        "ceilings": {
            "max_thesis_risk_pct": settings.cfd_max_thesis_risk_pct,
            "max_correlated_risk_pct": settings.cfd_max_correlated_risk_pct,
            "max_portfolio_risk_pct": settings.cfd_max_portfolio_risk_pct,
            "max_exposure_multiple": settings.cfd_max_exposure_multiple,
        },
    }


def _drawdown_summary(equity_estimate: float) -> dict:
    """Current drawdown tier and its risk multiplier, purely
    informational (the live scheduler already applies this every run --
    see trading.cfd.drawdown_monitor). equity_estimate is the same
    offline approximation _portfolio_risk_summary uses -- the persisted
    high_water_mark itself is exact (it's updated from real broker
    equity every live run), only the CURRENT equity read here is
    approximated."""
    tracking = get_equity_tracking()
    high_water_mark = tracking.get("high_water_mark")
    thresholds = DrawdownThresholds(
        moderate_pct=settings.cfd_drawdown_moderate_pct,
        deep_pct=settings.cfd_drawdown_deep_pct,
        severe_pct=settings.cfd_drawdown_severe_pct,
        moderate_multiplier=settings.cfd_drawdown_moderate_multiplier,
        deep_multiplier=settings.cfd_drawdown_deep_multiplier,
    )
    tier = classify_drawdown_tier(equity_estimate, high_water_mark or 0.0, thresholds)
    return {
        "equity_basis": round(equity_estimate, 2),
        "high_water_mark": high_water_mark,
        "smoothed_equity": tracking.get("smoothed_equity"),
        "tier": tier,
        "risk_multiplier": drawdown_risk_multiplier(tier, thresholds),
    }


def build_report(trades: list[dict], paper_trades: list[dict], starting_equity: Optional[float] = None) -> dict:
    """trades: trading.cfd.trade_log.load_trades()'s real Trade Database.
    paper_trades: the same, but from trading.cfd.paper_trading's separate
    log (state/cfd_paper_trades.jsonl). starting_equity defaults to
    CFD_VIRTUAL_STARTING_CAPITAL if not given."""
    starting_equity = starting_equity if starting_equity is not None else settings.cfd_virtual_starting_capital
    registry_entries = list_all()

    overall_performance = compute_performance(trades, starting_equity=starting_equity)
    loss_breakdown = summarize_losses(trades)
    active_entries = [e for e in registry_entries if e.state == LifecycleState.ACTIVE.value]
    allocation_summary = compute_allocations(trades, active_entries)
    equity_estimate = starting_equity + overall_performance.get("net_return", 0.0)
    portfolio_risk_summary = _portfolio_risk_summary(equity_estimate)
    drawdown_summary = _drawdown_summary(equity_estimate)

    recommendations = (
        _degradation_recommendations(trades, registry_entries)
        + _validated_awaiting_paper_recommendations(registry_entries)
        + _paper_promotion_recommendations(paper_trades, registry_entries)
    )

    decisions = load_decisions()
    incidents = load_incidents()
    decision_counts: dict[str, int] = {}
    regime_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    strategy_decision_counts: dict[str, int] = {}
    for row in decisions:
        key = row.get("outcome") or "UNKNOWN"
        decision_counts[key] = decision_counts.get(key, 0) + 1
        regime = row.get("regime") or "unknown"
        regime_counts[regime] = regime_counts.get(regime, 0) + 1
        reason = row.get("reason") or "unknown"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        strategy = row.get("strategy") or "none"
        strategy_decision_counts[strategy] = strategy_decision_counts.get(strategy, 0) + 1
    incident_counts: dict[str, int] = {}
    for row in incidents:
        key = row.get("kind") or "unknown"
        incident_counts[key] = incident_counts.get(key, 0) + 1

    return {
        "overall_performance": overall_performance,
        "loss_breakdown": loss_breakdown,
        "allocation_summary": allocation_summary,
        "portfolio_risk_summary": portfolio_risk_summary,
        "drawdown_summary": drawdown_summary,
        "decision_summary": {
            "total": len(decisions),
            "by_outcome": decision_counts,
            "by_regime": regime_counts,
            "by_reason": reason_counts,
            "by_strategy": strategy_decision_counts,
            "recent": decisions[-20:],
        },
        "opportunity_summary": {
            "market_evaluations": len(decisions),
            "trade_candidates": decision_counts.get("TRADE", 0),
            "no_trade": decision_counts.get("NO_TRADE", 0),
            "rejected": decision_counts.get("REJECTED", 0),
            "errors": decision_counts.get("ERROR", 0),
            "real_closed_trades": overall_performance.get("trade_count", 0),
            "paper_closed_trades": len([t for t in paper_trades if t.get("pnl") is not None]),
            "regime_mix": regime_counts,
            "top_blockers": sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:10],
        },
        "incident_summary": {
            "total": len(incidents),
            "by_kind": incident_counts,
            "recent": incidents[-20:],
        },
        "registry_summary": {
            state.value: [f"{e.name}@{e.version}" for e in registry_entries if e.state == state.value]
            for state in LifecycleState
        },
        "recommendations": [
            {"type": r.type, "strategy": r.strategy, "reason": r.reason, "command": r.command} for r in recommendations
        ],
    }

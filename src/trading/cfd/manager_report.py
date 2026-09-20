"""AI Trading Manager -- Management Report -- src/trading/cfd/manager_report.py

Ties together everything built so far (Trade Database, Performance
Engine, Failure Analysis, Strategy Registry, Research Lab, Paper Trading)
into one consolidated report: what's actually happening across every
registered strategy, and what still needs a human's attention.

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

from trading.cfd.failure_analysis import detect_degradation, summarize_losses
from trading.cfd.performance import compute_performance
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


def build_report(trades: list[dict], paper_trades: list[dict], starting_equity: Optional[float] = None) -> dict:
    """trades: trading.cfd.trade_log.load_trades()'s real Trade Database.
    paper_trades: the same, but from trading.cfd.paper_trading's separate
    log (state/cfd_paper_trades.jsonl). starting_equity defaults to
    CFD_VIRTUAL_STARTING_CAPITAL if not given."""
    starting_equity = starting_equity if starting_equity is not None else settings.cfd_virtual_starting_capital
    registry_entries = list_all()

    overall_performance = compute_performance(trades, starting_equity=starting_equity)
    loss_breakdown = summarize_losses(trades)

    recommendations = (
        _degradation_recommendations(trades, registry_entries)
        + _validated_awaiting_paper_recommendations(registry_entries)
        + _paper_promotion_recommendations(paper_trades, registry_entries)
    )

    return {
        "overall_performance": overall_performance,
        "loss_breakdown": loss_breakdown,
        "registry_summary": {
            state.value: [f"{e.name}@{e.version}" for e in registry_entries if e.state == state.value]
            for state in LifecycleState
        },
        "recommendations": [
            {"type": r.type, "strategy": r.strategy, "reason": r.reason, "command": r.command} for r in recommendations
        ],
    }

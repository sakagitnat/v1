"""AI Trading Manager -- Management Report -- src/trading/cfd/manager_report.py

Ties together everything Phases 0-4 built (Trade Database, Performance
Engine, Failure Analysis, Strategy Registry, Research Lab, Paper Trading)
into one consolidated report: what's actually happening across every
registered strategy, and what a human should consider doing about it.

This module NEVER takes action on its own -- it only recommends, in the
form of the exact `cfd_cli.py` command that would carry out each
suggestion. Every lifecycle change it surfaces still goes through that
command, with the same audited-reason requirement as any other manual
change (trading.cfd.strategy_registry.set_state()). Handing an AI
unrestricted authority to pause/promote/resize strategies on its own
would be exactly the kind of AI-overrides-the-Risk-Governor /
hot-edit-without-validation behavior docs/VISION.md forbids: the AI
decides BUY/SELL/NO TRADE and selects among already-ACTIVE strategies
(both already automated -- see trading.cfd.selector), but strategy
lifecycle changes stay a deliberate, audited human action, same as every
phase before this one.

Recommendations are deterministic and fully explained -- no black box:
every one names the specific number(s) that triggered it.
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
    recs = []
    for entry in registry_entries:
        if entry.state != LifecycleState.ACTIVE.value:
            continue
        tag = f"{entry.name}@{entry.version}"
        result = detect_degradation(trades, tag)
        if result and result["degraded"]:
            recs.append(
                Recommendation(
                    type="pause_degraded_strategy",
                    strategy=tag,
                    reason=result["reason"],
                    command=f"cfd_cli.py promote-strategy {entry.name} {entry.version} PAUSED --reason \"degradation: {result['reason']}\"",
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

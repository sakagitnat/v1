"""Qualification Gate -- src/trading/cfd/qualification_gate.py

Closes Revision 3 gap #10 (docs/ARCHITECTURE_AUDIT.md): docs/VISION.md's
"Qualification Gate before real money" section is explicit that the
system must never simply ASSERT it's ready for real money -- it must
show, measurably, a checklist of evidence, and even a full PASS is
evidence for a human to weigh, never itself the approval
(`CFD_ALLOW_LIVE_TRADING` is still always a human's own decision -- see
docs/VISION.md's "Autonomy boundaries").

Before this module, `research_lab.py` (backtest/walk-forward/Monte
Carlo), `paper_trading.py` (forward simulation), and the Strategy
Registry's own audit trail each held ONE piece of the evidence
docs/VISION.md's checklist asks for, with nothing that read across all
of them and reported a single, itemized verdict. qualify() is that
consolidation -- read-only, changes nothing, decides nothing on its own.

Every criterion below is checked against data this project ACTUALLY
persists in a structured, queryable form -- trade logs, paper trade
logs, the registry's own history -- never a number this module invents
or assumes. Two of docs/VISION.md's nine listed criteria
(risk-controls-actually-fired-under-test, no-duplicate-execution-
incidents) can't be verified this way today: nothing in this codebase
persists a structured log of "the Portfolio Risk Governor rejected an
entry" or "a pending-entry adoption ever happened" -- those events are
only ever logged to stdout/GitHub Actions logs, not written to a
queryable record. Rather than claim a check that isn't real, this
module reports those two as UNVERIFIABLE (never silently passed, never
silently dropped), naming exactly why -- a genuinely qualified strategy
still needs a human to read the operational logs for that evidence
until this project builds a structured incident log to check instead.
"""
from dataclasses import dataclass, field
from typing import Optional

from trading.cfd.paper_trading import PAPER_LOG_PATH
from trading.cfd.performance import compute_performance
from trading.cfd.strategy_registry import LifecycleState, get
from trading.cfd.trade_log import load_trades
from trading.config import settings

PASS = "pass"
FAIL = "fail"
INSUFFICIENT_DATA = "insufficient_data"
NOT_APPLICABLE = "not_applicable"
UNVERIFIABLE = "unverifiable"

MIN_TRADES_FOR_EVIDENCE = 20
"""Same bar research_lab.py's TRAIN gate and manager_report.py's paper-
promotion check already use -- not independently re-derived here."""

MIN_DISTINCT_REGIMES = 2
"""How many different trading.cfd.regime labels the strategy's own trade
history must span before "passed multiple market regimes" counts as
demonstrated, not just asserted from a single lucky/unlucky stretch."""

MAX_QUALIFYING_DRAWDOWN_PCT = -25.0
"""Same cap research_lab.py's own candidate gate already uses
(MAX_DRAWDOWN_CAP) -- not a new, independently chosen number."""


@dataclass
class Criterion:
    name: str
    status: str  # PASS / FAIL / INSUFFICIENT_DATA / NOT_APPLICABLE / UNVERIFIABLE
    detail: str


@dataclass
class QualificationReport:
    strategy: str
    verdict: str  # "ready_for_human_review", "not_yet", or "unknown_strategy"
    criteria: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "verdict": self.verdict,
            "criteria": [{"name": c.name, "status": c.status, "detail": c.detail} for c in self.criteria],
        }


def _own_trades(trades: list[dict], tag: str) -> list[dict]:
    return [t for t in trades if t.get("strategy") == tag and t.get("pnl") is not None]


def _expectancy_criterion(trades: list[dict], label: str) -> Criterion:
    if len(trades) < MIN_TRADES_FOR_EVIDENCE:
        return Criterion(
            "positive_expectancy_net_of_costs", INSUFFICIENT_DATA,
            f"only {len(trades)} priced {label} trade(s), need >= {MIN_TRADES_FOR_EVIDENCE} to mean anything",
        )
    perf = compute_performance(trades, starting_equity=settings.cfd_virtual_starting_capital)
    ok = perf["expectancy"] > 0
    return Criterion(
        "positive_expectancy_net_of_costs",
        PASS if ok else FAIL,
        f"{label}: {len(trades)} trades, expectancy {perf['expectancy']:+.2f}, win rate {perf['win_rate_pct']:.1f}%",
    )


def _regime_diversity_criterion(trades: list[dict], label: str) -> Criterion:
    if len(trades) < MIN_TRADES_FOR_EVIDENCE:
        return Criterion(
            "passed_multiple_regimes", INSUFFICIENT_DATA,
            f"only {len(trades)} priced {label} trade(s), need >= {MIN_TRADES_FOR_EVIDENCE} to mean anything",
        )
    perf = compute_performance(trades, starting_equity=settings.cfd_virtual_starting_capital)
    regimes = {name for name in perf["by_regime"] if name not in ("unknown", None)}
    ok = len(regimes) >= MIN_DISTINCT_REGIMES
    return Criterion(
        "passed_multiple_regimes",
        PASS if ok else FAIL,
        f"{label}: traded through {len(regimes)} distinct regime(s) ({sorted(regimes)}), need >= {MIN_DISTINCT_REGIMES}",
    )


def _drawdown_criterion(trades: list[dict], label: str) -> Criterion:
    if len(trades) < MIN_TRADES_FOR_EVIDENCE:
        return Criterion(
            "drawdown_within_envelope", INSUFFICIENT_DATA,
            f"only {len(trades)} priced {label} trade(s), need >= {MIN_TRADES_FOR_EVIDENCE} to mean anything",
        )
    perf = compute_performance(trades, starting_equity=settings.cfd_virtual_starting_capital)
    ok = perf["max_drawdown_pct"] >= MAX_QUALIFYING_DRAWDOWN_PCT
    return Criterion(
        "drawdown_within_envelope",
        PASS if ok else FAIL,
        f"{label}: max drawdown {perf['max_drawdown_pct']}%, envelope is {MAX_QUALIFYING_DRAWDOWN_PCT}%",
    )


def _out_of_sample_criterion(history: list[dict]) -> Criterion:
    for h in history:
        reason = h.get("reason", "")
        if "TEST cagr" in reason or "out-of-sample" in reason.lower() or "TRAIN/TEST-validated" in reason:
            return Criterion(
                "passed_out_of_sample", PASS,
                f"registry audit trail records out-of-sample evidence: \"{reason}\"",
            )
    return Criterion(
        "passed_out_of_sample", FAIL,
        "no registry history entry records TEST/out-of-sample evidence for this version",
    )


def _version_frozen_criterion() -> Criterion:
    return Criterion(
        "strategy_version_frozen_during_qualification", PASS,
        "structurally guaranteed: strategy_registry.register() refuses to overwrite an existing "
        "(name, version) -- a parameter change is always a new version, never a silent edit of this one",
    )


def _never_demoted_criterion(history: list[dict]) -> Criterion:
    demotions = [h for h in history if h.get("to") == "PAUSED" and "autonomous demotion" in h.get("reason", "")]
    if not demotions:
        return Criterion(
            "no_safety_rule_violations", PASS,
            "no autonomous demotion ever recorded against this version's registry history",
        )
    return Criterion(
        "no_safety_rule_violations", FAIL,
        f"decay_supervisor autonomously demoted this version {len(demotions)} time(s) -- "
        f"most recent: \"{demotions[-1]['reason']}\" at {demotions[-1].get('at')}",
    )


def _live_vs_paper_criterion(entry, paper_trades_own: list[dict]) -> Criterion:
    if entry.state != LifecycleState.ACTIVE.value:
        return Criterion(
            "live_demo_behavior_not_diverged", NOT_APPLICABLE,
            f"strategy is {entry.state}, not yet ACTIVE -- no live behavior exists yet to compare",
        )
    promoted_at = next((h.get("at") for h in entry.history if h.get("to") == "ACTIVE"), None)
    live_trades = _own_trades(load_trades(), f"{entry.name}@{entry.version}")
    if not promoted_at or len(live_trades) < MIN_TRADES_FOR_EVIDENCE or len(paper_trades_own) < MIN_TRADES_FOR_EVIDENCE:
        return Criterion(
            "live_demo_behavior_not_diverged", INSUFFICIENT_DATA,
            f"{len(live_trades)} live trade(s) since promotion, {len(paper_trades_own)} paper trade(s) on record -- "
            f"need >= {MIN_TRADES_FOR_EVIDENCE} of each to compare meaningfully",
        )
    paper_before = [t for t in paper_trades_own if t.get("exit_time", "") <= promoted_at]
    live_perf = compute_performance(live_trades, starting_equity=settings.cfd_virtual_starting_capital)
    paper_perf = compute_performance(paper_before, starting_equity=settings.cfd_virtual_starting_capital)
    live_wr, paper_wr = live_perf["win_rate_pct"], paper_perf["win_rate_pct"]
    diverged = abs(live_wr - paper_wr) > 25.0  # a generous, stated-not-validated tolerance band
    return Criterion(
        "live_demo_behavior_not_diverged",
        FAIL if diverged else PASS,
        f"live win rate {live_wr:.1f}% vs paper (pre-promotion) win rate {paper_wr:.1f}% "
        f"({'diverges' if diverged else 'within'} the 25pp tolerance band)",
    )


def qualify(name: str, version: str) -> QualificationReport:
    """Consolidates every checkable piece of docs/VISION.md's
    Qualification Gate evidence for one strategy version into a single
    report. Never itself a promotion or a live-trading decision --
    CFD_ALLOW_LIVE_TRADING stays a human's own call regardless of the
    verdict here."""
    tag = f"{name}@{version}"
    entry = get(name, version)
    if entry is None:
        return QualificationReport(strategy=tag, verdict="unknown_strategy", criteria=[])

    paper_trades_own = _own_trades(load_trades(PAPER_LOG_PATH), tag)
    live_trades_own = _own_trades(load_trades(), tag)
    # Prefer live evidence once there's enough of it; paper is the only
    # evidence available before ACTIVE, and stays the fallback after if
    # live history is still too thin on its own.
    evidence_trades, evidence_label = (
        (live_trades_own, "live") if len(live_trades_own) >= MIN_TRADES_FOR_EVIDENCE else (paper_trades_own, "paper")
    )

    criteria = [
        _expectancy_criterion(evidence_trades, evidence_label),
        _out_of_sample_criterion(entry.history),
        _regime_diversity_criterion(evidence_trades, evidence_label),
        _drawdown_criterion(evidence_trades, evidence_label),
        _version_frozen_criterion(),
        _never_demoted_criterion(entry.history),
        _live_vs_paper_criterion(entry, paper_trades_own),
        Criterion(
            "risk_controls_fired_correctly_under_test", UNVERIFIABLE,
            "no structured log of Portfolio Risk Governor rejections exists yet -- only stdout/GitHub "
            "Actions log lines. Review the scheduler's run logs manually for this strategy's rejections, "
            "or treat this as still-open work (see docs/ARCHITECTURE_AUDIT.md).",
        ),
        Criterion(
            "no_duplicate_execution_incidents", UNVERIFIABLE,
            "no structured log of pending-entry adoptions/foreign-position detections exists yet -- only "
            "stdout/GitHub Actions log lines. Review the scheduler's run logs manually for this strategy, "
            "or treat this as still-open work (see docs/ARCHITECTURE_AUDIT.md).",
        ),
    ]

    if any(c.status == FAIL for c in criteria):
        verdict = "not_yet"
    elif any(c.status == INSUFFICIENT_DATA for c in criteria):
        verdict = "not_yet"
    else:
        verdict = "ready_for_human_review"

    return QualificationReport(strategy=tag, verdict=verdict, criteria=criteria)

from trading.cfd import qualification_gate as qg
from trading.cfd import strategy_registry as reg
from trading.cfd import trade_log
from trading.cfd.qualification_gate import (
    FAIL,
    INSUFFICIENT_DATA,
    NOT_APPLICABLE,
    PASS,
    UNVERIFIABLE,
    qualify,
)
from trading.cfd.strategy_registry import LifecycleState


def _use_tmp_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")
    monkeypatch.setattr(trade_log, "_LOG_PATH", tmp_path / "cfd_trades.jsonl")
    monkeypatch.setattr(qg, "PAPER_LOG_PATH", tmp_path / "cfd_paper_trades.jsonl")


def _trade(pnl, strategy, contract_id, regime="trending", exit_time="2026-01-01T01:00:00+00:00",
           entry_time="2026-01-01T00:00:00+00:00"):
    return {
        "contract_id": contract_id, "instrument": "frxXAUUSD", "strategy": strategy, "side": "long",
        "entry_time": entry_time, "exit_time": exit_time, "entry_price": 2000.0, "stake": 10.0,
        "risk_amount": 1.0, "exit_price": 2010.0, "pnl": pnl, "regime": regime,
    }


def _paper_trades(tag, n, pnl=1.0, regimes=("trending", "ranging")):
    return [
        _trade(pnl, tag, i, regime=regimes[i % len(regimes)], exit_time=f"2026-01-01T{i % 24:02d}:00:00+00:00")
        for i in range(n)
    ]


def test_unknown_strategy_returns_unknown_strategy_verdict(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    report = qualify("nope", "v1")
    assert report.verdict == "unknown_strategy"
    assert report.criteria == []


def test_freshly_registered_candidate_is_insufficient_data(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.CANDIDATE)
    report = qualify("a", "v1")
    assert report.verdict == "not_yet"
    expectancy = next(c for c in report.criteria if c.name == "positive_expectancy_net_of_costs")
    assert expectancy.status == INSUFFICIENT_DATA


def test_two_criteria_are_always_reported_unverifiable(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.CANDIDATE)
    report = qualify("a", "v1")
    names = {c.name: c.status for c in report.criteria}
    assert names["risk_controls_fired_correctly_under_test"] == UNVERIFIABLE
    assert names["no_duplicate_execution_incidents"] == UNVERIFIABLE


def test_version_frozen_criterion_always_passes_structurally(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.CANDIDATE)
    report = qualify("a", "v1")
    frozen = next(c for c in report.criteria if c.name == "strategy_version_frozen_during_qualification")
    assert frozen.status == PASS


def test_paper_strategy_with_enough_good_diverse_trades_looks_ready(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.PAPER, note="TEST cagr=8.0% maxdd=-12.0%")
    import json
    tag = "a@v1"
    trades = _paper_trades(tag, 25, pnl=2.0)
    qg.PAPER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with qg.PAPER_LOG_PATH.open("w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")

    report = qualify("a", "v1")
    by_name = {c.name: c for c in report.criteria}
    assert by_name["positive_expectancy_net_of_costs"].status == PASS
    assert by_name["passed_multiple_regimes"].status == PASS
    assert by_name["drawdown_within_envelope"].status == PASS
    assert by_name["passed_out_of_sample"].status == PASS
    assert by_name["live_demo_behavior_not_diverged"].status == NOT_APPLICABLE  # not ACTIVE yet
    assert report.verdict == "ready_for_human_review"


def test_losing_strategy_fails_expectancy_and_overall_verdict(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.PAPER)
    import json
    tag = "a@v1"
    trades = _paper_trades(tag, 25, pnl=-2.0)
    qg.PAPER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with qg.PAPER_LOG_PATH.open("w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")

    report = qualify("a", "v1")
    expectancy = next(c for c in report.criteria if c.name == "positive_expectancy_net_of_costs")
    assert expectancy.status == FAIL
    assert report.verdict == "not_yet"


def test_single_regime_trade_history_fails_regime_diversity(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.PAPER)
    import json
    tag = "a@v1"
    trades = _paper_trades(tag, 25, pnl=2.0, regimes=("trending",))
    qg.PAPER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with qg.PAPER_LOG_PATH.open("w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")

    report = qualify("a", "v1")
    regime_check = next(c for c in report.criteria if c.name == "passed_multiple_regimes")
    assert regime_check.status == FAIL


def test_out_of_sample_criterion_fails_with_no_evidence_in_history(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.CANDIDATE, note="just a candidate, nothing tested")
    report = qualify("a", "v1")
    oos = next(c for c in report.criteria if c.name == "passed_out_of_sample")
    assert oos.status == FAIL


def test_grandfathered_note_satisfies_out_of_sample_criterion(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, note="Grandfathered: TRAIN/TEST-validated (see README).")
    report = qualify("a", "v1")
    oos = next(c for c in report.criteria if c.name == "passed_out_of_sample")
    assert oos.status == PASS


def test_autonomous_demotion_in_history_fails_safety_criterion(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE)
    reg.set_state("a", "v1", LifecycleState.PAUSED, reason="autonomous demotion: expectancy dropped")
    report = qualify("a", "v1")
    safety = next(c for c in report.criteria if c.name == "no_safety_rule_violations")
    assert safety.status == FAIL
    assert report.verdict == "not_yet"


def test_active_strategy_with_no_live_history_yet_is_insufficient_for_deviation_check(tmp_path, monkeypatch):
    _use_tmp_paths(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE)
    report = qualify("a", "v1")
    deviation = next(c for c in report.criteria if c.name == "live_demo_behavior_not_diverged")
    assert deviation.status == INSUFFICIENT_DATA

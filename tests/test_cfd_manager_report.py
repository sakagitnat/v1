from trading.cfd import state, strategy_registry as reg
from trading.cfd.manager_report import build_report
from trading.cfd.strategy_registry import LifecycleState


def _use_tmp_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")
    # build_report() now also reads trading.cfd.state.list_open_trades()
    # for the Portfolio Risk Governor summary -- isolate that too, or
    # every test here would read the real production state file.
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")


def _trade(pnl, strategy="ema_crossover@v1", contract_id=1, exit_time="2026-01-01T01:00:00+00:00",
           entry_time="2026-01-01T00:00:00+00:00", risk_amount=1.0):
    return {
        "contract_id": contract_id, "instrument": "frxXAUUSD", "strategy": strategy, "side": "long",
        "entry_time": entry_time, "exit_time": exit_time, "entry_price": 2000.0, "stake": 10.0,
        "risk_amount": risk_amount, "exit_price": 2010.0, "pnl": pnl,
        "equity_before": 100.0, "equity_after": 100.0 + (pnl or 0), "exit_reason": "test", "regime": "trending",
    }


def test_report_with_no_data_is_empty_but_does_not_crash(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    report = build_report([], [])
    assert report["overall_performance"]["trade_count"] == 0
    assert report["loss_breakdown"] == {}
    assert report["recommendations"] == []
    assert report["allocation_summary"] == {}
    assert report["portfolio_risk_summary"]["open_position_count"] == 0
    assert report["portfolio_risk_summary"]["total_portfolio_risk"] == 0.0
    assert report["drawdown_summary"]["tier"] == "normal"
    assert report["drawdown_summary"]["high_water_mark"] is None
    assert all(v == [] for v in report["registry_summary"].values())


def test_portfolio_risk_summary_aggregates_currently_open_positions(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    state.record_open_trade(1, {
        "instrument": "frxXAUUSD", "side": "long", "risk_amount": 1.5, "stake": 30.0, "multiplier": 20,
    })
    state.record_open_trade(2, {
        "instrument": "frxEURUSD", "side": "long", "risk_amount": 1.0, "stake": 20.0, "multiplier": 20,
    })
    report = build_report([], [])
    summary = report["portfolio_risk_summary"]
    assert summary["open_position_count"] == 2
    assert summary["total_portfolio_risk"] == 2.5
    assert summary["thesis_risk"]["frxXAUUSD:long"] == 1.5
    assert summary["thesis_risk"]["frxEURUSD:long"] == 1.0
    assert summary["correlated_risk"]["usd:short"] == 2.5  # both are "USD weakens" bets
    assert summary["total_notional_exposure"] == 1000.0  # (30*20) + (20*20)
    assert summary["ceilings"]["max_portfolio_risk_pct"] > 0


def test_drawdown_summary_reflects_a_persisted_high_water_mark(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    state.set_equity_tracking(smoothed_equity=95.0, high_water_mark=100.0)
    # starting_equity default (CFD_VIRTUAL_STARTING_CAPITAL) with no
    # trades means equity_estimate == starting_equity -- below the
    # persisted 100.0 high-water-mark, so a real drawdown should show.
    report = build_report([], [], starting_equity=90.0)
    summary = report["drawdown_summary"]
    assert summary["high_water_mark"] == 100.0
    assert summary["smoothed_equity"] == 95.0
    assert summary["tier"] in {"moderate", "deep", "severe"}  # 10% drawdown at default thresholds
    assert summary["risk_multiplier"] < 1.0


def test_registry_summary_groups_by_state(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    reg.register("b", "v1", {}, initial_state=LifecycleState.CANDIDATE)
    report = build_report([], [])
    assert report["registry_summary"]["ACTIVE"] == ["a@v1"]
    assert report["registry_summary"]["CANDIDATE"] == ["b@v1"]


def test_allocation_summary_weights_active_strategies(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    reg.register("b", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["ranging"])
    reg.register("c", "v1", {}, initial_state=LifecycleState.CANDIDATE)  # not ACTIVE -- excluded
    report = build_report([], [])
    assert set(report["allocation_summary"].keys()) == {"a@v1", "b@v1"}
    assert abs(sum(report["allocation_summary"].values()) - 1.0) < 1e-9


def test_flags_a_degraded_active_strategy_pending_autonomous_demotion(tmp_path, monkeypatch):
    # decay_supervisor.run_autonomous_demotion() (called by the live
    # scheduler, not build_report) is what actually demotes it -- this
    # report just surfaces it as informational until that next run happens.
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("ema_crossover", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])

    prior = [_trade(pnl=2.0, contract_id=i, exit_time=f"2026-01-01T{i:02d}:00:00+00:00") for i in range(10)]
    recent = [_trade(pnl=-1.0, contract_id=100 + i, exit_time=f"2026-01-02T{i:02d}:00:00+00:00") for i in range(10)]

    report = build_report(prior + recent, [])
    pause_recs = [r for r in report["recommendations"] if r["type"] == "degrading_strategy_pending_autonomous_demotion"]
    assert len(pause_recs) == 1
    assert pause_recs[0]["strategy"] == "ema_crossover@v1"
    assert "promote-strategy ema_crossover v1 PAUSED" in pause_recs[0]["command"]


def test_recommends_advancing_validated_strategy_to_paper(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("donchian_breakout", "v2", {}, initial_state=LifecycleState.VALIDATED, regimes=["trending"])

    report = build_report([], [])
    recs = [r for r in report["recommendations"] if r["type"] == "advance_validated_to_paper"]
    assert len(recs) == 1
    assert recs[0]["strategy"] == "donchian_breakout@v2"
    assert "PAPER" in recs[0]["command"]


def test_recommends_promoting_a_healthy_paper_strategy(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("donchian_breakout", "v2", {}, initial_state=LifecycleState.PAPER, regimes=["trending"])

    paper_trades = [_trade(pnl=1.0, strategy="donchian_breakout@v2", contract_id=i,
                            exit_time=f"2026-01-01T{i % 24:02d}:00:00+00:00") for i in range(25)]

    report = build_report([], paper_trades)
    recs = [r for r in report["recommendations"] if r["type"] == "consider_promoting_paper_strategy"]
    assert len(recs) == 1
    assert recs[0]["strategy"] == "donchian_breakout@v2"
    assert "ACTIVE" in recs[0]["command"]


def test_does_not_recommend_promoting_paper_strategy_with_too_few_trades(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("donchian_breakout", "v2", {}, initial_state=LifecycleState.PAPER, regimes=["trending"])
    paper_trades = [_trade(pnl=1.0, strategy="donchian_breakout@v2", contract_id=i) for i in range(5)]

    report = build_report([], paper_trades)
    recs = [r for r in report["recommendations"] if r["type"] == "consider_promoting_paper_strategy"]
    assert recs == []


def test_does_not_recommend_promoting_a_losing_paper_strategy(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("donchian_breakout", "v2", {}, initial_state=LifecycleState.PAPER, regimes=["trending"])
    paper_trades = [_trade(pnl=-1.0, strategy="donchian_breakout@v2", contract_id=i,
                            exit_time=f"2026-01-01T{i % 24:02d}:00:00+00:00") for i in range(25)]

    report = build_report([], paper_trades)
    recs = [r for r in report["recommendations"] if r["type"] == "consider_promoting_paper_strategy"]
    assert recs == []

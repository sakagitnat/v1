from trading.cfd import strategy_registry as reg
from trading.cfd.manager_report import build_report
from trading.cfd.strategy_registry import LifecycleState


def _use_tmp_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")


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
    assert all(v == [] for v in report["registry_summary"].values())


def test_registry_summary_groups_by_state(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    reg.register("b", "v1", {}, initial_state=LifecycleState.CANDIDATE)
    report = build_report([], [])
    assert report["registry_summary"]["ACTIVE"] == ["a@v1"]
    assert report["registry_summary"]["CANDIDATE"] == ["b@v1"]


def test_recommends_pausing_a_degraded_active_strategy(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("ema_crossover", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])

    prior = [_trade(pnl=2.0, contract_id=i, exit_time=f"2026-01-01T{i:02d}:00:00+00:00") for i in range(10)]
    recent = [_trade(pnl=-1.0, contract_id=100 + i, exit_time=f"2026-01-02T{i:02d}:00:00+00:00") for i in range(10)]

    report = build_report(prior + recent, [])
    pause_recs = [r for r in report["recommendations"] if r["type"] == "pause_degraded_strategy"]
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

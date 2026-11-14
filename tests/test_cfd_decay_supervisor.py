from trading.cfd import strategy_registry as reg
from trading.cfd.decay_supervisor import run_autonomous_demotion
from trading.cfd.strategy_registry import LifecycleState


def _use_tmp_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")


def _trade(pnl, strategy, contract_id, exit_time, risk_amount=1.0):
    return {
        "contract_id": contract_id,
        "instrument": "frxXAUUSD",
        "strategy": strategy,
        "side": "long",
        "entry_time": "2026-01-01T00:00:00+00:00",
        "exit_time": exit_time,
        "entry_price": 2000.0,
        "stake": 10.0,
        "risk_amount": risk_amount,
        "pnl": pnl,
        "regime": "trending",
    }


def _degrading_trades(strategy_tag: str) -> list[dict]:
    prior = [_trade(2.0, strategy_tag, i, f"2026-01-01T{i:02d}:00:00+00:00") for i in range(10)]
    recent = [_trade(-1.0, strategy_tag, 100 + i, f"2026-01-02T{i:02d}:00:00+00:00") for i in range(10)]
    return prior + recent


def _stable_trades(strategy_tag: str) -> list[dict]:
    return [_trade(1.0, strategy_tag, i, f"2026-01-01T{i:02d}:00:00+00:00") for i in range(20)]


def test_no_active_strategies_means_no_demotions(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.CANDIDATE, regimes=["trending"])
    assert run_autonomous_demotion([]) == []
    assert reg.get("a", "v1").state == "CANDIDATE"


def test_degraded_active_strategy_is_demoted(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("ema_crossover", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    trades = _degrading_trades("ema_crossover@v1")

    demotions = run_autonomous_demotion(trades)

    assert len(demotions) == 1
    assert demotions[0]["strategy"] == "ema_crossover@v1"
    assert "autonomous demotion" in demotions[0]["reason"]
    entry = reg.get("ema_crossover", "v1")
    assert entry.state == "PAUSED"
    assert entry.history[-1]["reason"] == demotions[0]["reason"]
    assert entry.history[-1]["from"] == "ACTIVE"
    assert entry.history[-1]["to"] == "PAUSED"


def test_healthy_active_strategy_is_not_demoted(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("ema_crossover", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    trades = _stable_trades("ema_crossover@v1")

    demotions = run_autonomous_demotion(trades)

    assert demotions == []
    assert reg.get("ema_crossover", "v1").state == "ACTIVE"


def test_strategy_with_too_little_history_is_not_demoted(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("ema_crossover", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    trades = [_trade(-1.0, "ema_crossover@v1", i, f"2026-01-01T{i:02d}:00:00+00:00") for i in range(3)]

    demotions = run_autonomous_demotion(trades)

    assert demotions == []
    assert reg.get("ema_crossover", "v1").state == "ACTIVE"


def test_non_active_strategies_are_never_touched_even_with_degrading_trades(tmp_path, monkeypatch):
    # e.g. paper-trading history for a VALIDATED/PAPER strategy -- never
    # live, so demoting it would mean nothing; must be ignored entirely.
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("donchian_breakout", "v2", {}, initial_state=LifecycleState.PAPER, regimes=["trending"])
    trades = _degrading_trades("donchian_breakout@v2")

    demotions = run_autonomous_demotion(trades)

    assert demotions == []
    assert reg.get("donchian_breakout", "v2").state == "PAPER"


def test_only_the_degraded_strategy_among_several_active_ones_is_demoted(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    reg.register("b", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["ranging"])
    trades = _degrading_trades("a@v1") + _stable_trades("b@v1")

    demotions = run_autonomous_demotion(trades)

    assert len(demotions) == 1
    assert demotions[0]["strategy"] == "a@v1"
    assert reg.get("a", "v1").state == "PAUSED"
    assert reg.get("b", "v1").state == "ACTIVE"

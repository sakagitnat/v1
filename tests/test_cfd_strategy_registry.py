import pytest

from trading.cfd import strategy_registry as reg
from trading.cfd.breakout import DonchianBreakoutStrategy
from trading.cfd.strategy import EmaCrossoverStrategy
from trading.cfd.strategy_registry import LifecycleState


def _use_tmp_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")


def test_register_then_get_roundtrips(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("ema_crossover", "v1", {"fast_span": 15}, initial_state=LifecycleState.RESEARCH)
    entry = reg.get("ema_crossover", "v1")
    assert entry.name == "ema_crossover"
    assert entry.version == "v1"
    assert entry.params == {"fast_span": 15}
    assert entry.state == "RESEARCH"


def test_get_missing_returns_none(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    assert reg.get("nope", "v1") is None


def test_register_refuses_to_overwrite_existing_version(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("ema_crossover", "v1", {"fast_span": 15})
    with pytest.raises(ValueError):
        reg.register("ema_crossover", "v1", {"fast_span": 99})


def test_register_can_seed_any_initial_state_directly(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("ema_crossover", "v1", {}, initial_state=LifecycleState.ACTIVE, note="grandfathered")
    assert reg.get("ema_crossover", "v1").state == "ACTIVE"


def test_build_instantiates_the_right_class_with_params(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("ema_crossover", "v1", {"fast_span": 7, "slow_span": 21})
    strategy = reg.get("ema_crossover", "v1").build()
    assert isinstance(strategy, EmaCrossoverStrategy)
    assert strategy.fast_span == 7
    assert strategy.slow_span == 21

    reg.register("donchian_breakout", "v1", {"entry_window": 20})
    breakout = reg.get("donchian_breakout", "v1").build()
    assert isinstance(breakout, DonchianBreakoutStrategy)
    assert breakout.entry_window == 20


def test_build_unknown_strategy_name_raises(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("mystery_strategy", "v1", {})
    with pytest.raises(ValueError):
        reg.get("mystery_strategy", "v1").build()


def test_forward_pipeline_must_advance_one_stage_at_a_time(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("s", "v1", {})  # starts RESEARCH
    with pytest.raises(ValueError):
        reg.set_state("s", "v1", LifecycleState.ACTIVE, reason="skip ahead")  # not allowed to skip stages

    reg.set_state("s", "v1", LifecycleState.CANDIDATE, reason="passed backtest")
    reg.set_state("s", "v1", LifecycleState.VALIDATED, reason="passed out-of-sample")
    reg.set_state("s", "v1", LifecycleState.PAPER, reason="passed walk-forward + Monte Carlo")
    entry = reg.set_state("s", "v1", LifecycleState.ACTIVE, reason="passed paper trading")
    assert entry.state == "ACTIVE"
    assert len(entry.history) == 5  # registration + 4 transitions


def test_set_state_requires_a_reason(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("s", "v1", {})
    with pytest.raises(ValueError):
        reg.set_state("s", "v1", LifecycleState.CANDIDATE, reason="")


def test_pause_only_reachable_from_active(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("s", "v1", {})  # RESEARCH
    with pytest.raises(ValueError):
        reg.set_state("s", "v1", LifecycleState.PAUSED, reason="pause from research?")

    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE)
    paused = reg.set_state("a", "v1", LifecycleState.PAUSED, reason="market too volatile")
    assert paused.state == "PAUSED"
    resumed = reg.set_state("a", "v1", LifecycleState.ACTIVE, reason="conditions normalized")
    assert resumed.state == "ACTIVE"


def test_retired_is_terminal_and_reachable_from_anywhere(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("s", "v1", {})  # RESEARCH
    retired = reg.set_state("s", "v1", LifecycleState.RETIRED, reason="dead end")
    assert retired.state == "RETIRED"
    with pytest.raises(ValueError):
        reg.set_state("s", "v1", LifecycleState.RESEARCH, reason="revive")


def test_set_state_unknown_strategy_raises(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        reg.set_state("nope", "v1", LifecycleState.CANDIDATE, reason="x")


def test_get_active_strategy_raises_when_none_active(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("s", "v1", {})  # RESEARCH, not ACTIVE
    with pytest.raises(RuntimeError):
        reg.get_active_strategy()


def test_get_active_strategy_raises_when_multiple_active(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE)
    reg.register("b", "v1", {}, initial_state=LifecycleState.ACTIVE)
    with pytest.raises(RuntimeError):
        reg.get_active_strategy()


def test_get_active_strategy_returns_the_sole_active_entry(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.CANDIDATE)
    reg.register("b", "v1", {}, initial_state=LifecycleState.ACTIVE)
    assert reg.get_active_strategy().name == "b"


def test_list_by_state_filters_correctly(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.CANDIDATE)
    reg.register("b", "v1", {}, initial_state=LifecycleState.ACTIVE)
    reg.register("c", "v1", {}, initial_state=LifecycleState.CANDIDATE)
    candidates = reg.list_by_state(LifecycleState.CANDIDATE)
    assert {e.name for e in candidates} == {"a", "c"}

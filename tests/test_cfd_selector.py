import pytest

from trading.cfd import strategy_registry as reg
from trading.cfd.regime import RANGING, TRENDING, UNKNOWN
from trading.cfd.selector import select_for_entry
from trading.cfd.strategy_registry import LifecycleState


def _use_tmp_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")


def test_unknown_regime_is_always_no_trade(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    assert select_for_entry(UNKNOWN) is None


def test_matching_active_strategy_is_selected(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("trend_bot", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    entry = select_for_entry(TRENDING)
    assert entry.name == "trend_bot"


def test_no_active_strategy_suited_to_regime_is_no_trade(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("trend_bot", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    assert select_for_entry(RANGING) is None  # no mean-reversion strategy registered


def test_candidate_strategies_are_never_selected_even_if_regime_matches(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("untested", "v1", {}, initial_state=LifecycleState.CANDIDATE, regimes=["trending"])
    assert select_for_entry(TRENDING) is None


def test_multiple_active_matches_for_same_regime_raises(tmp_path, monkeypatch):
    # Should be unreachable via the normal registry API (set_state/register
    # enforce this at promotion time), but the selector still guards
    # against it directly rather than silently picking one.
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    reg.register("b", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["ranging"])  # disjoint -- registers fine
    # Simulate a corrupted/hand-edited state file bypassing the registry's
    # own overlap guard (register()/set_state() would refuse this directly).
    import json

    raw = json.loads(reg._REGISTRY_PATH.read_text())
    raw["b@v1"]["suited_regimes"] = ["trending"]
    reg._REGISTRY_PATH.write_text(json.dumps(raw))
    with pytest.raises(RuntimeError):
        select_for_entry(TRENDING)

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


def test_multiple_active_matches_picks_the_higher_weighted_one(tmp_path, monkeypatch):
    # Per docs/VISION.md's revised Portfolio/Allocation stage, several
    # ACTIVE strategies can share a regime now -- the selector breaks the
    # tie using trading.cfd.portfolio_allocator's weights, not by raising.
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    reg.register("b", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    entry = select_for_entry(TRENDING, allocations={"a@v1": 0.3, "b@v1": 0.7})
    assert entry.name == "b"


def test_multiple_active_matches_with_no_allocations_is_still_deterministic(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    reg.register("b", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    first = select_for_entry(TRENDING)
    second = select_for_entry(TRENDING)
    assert first.name == second.name


def test_exclude_tags_skips_a_strategy_already_positioned_on_this_instrument(tmp_path, monkeypatch):
    # Revision 3 gap #3: an instrument is no longer capped at one open
    # position -- a strategy that already has a leg open here is excluded,
    # but a genuinely different ACTIVE strategy suited to the same regime
    # is still selectable for its own independent position.
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    reg.register("b", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    entry = select_for_entry(TRENDING, exclude_tags={"a@v1"})
    assert entry.name == "b"


def test_exclude_tags_covering_every_match_is_no_trade(tmp_path, monkeypatch):
    _use_tmp_registry(tmp_path, monkeypatch)
    reg.register("a", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    assert select_for_entry(TRENDING, exclude_tags={"a@v1"}) is None

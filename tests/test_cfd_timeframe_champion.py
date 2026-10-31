import pytest

from trading.cfd import state as state_module
from trading.cfd.timeframe_champion import (
    CHAMPION_SPECS,
    MANAGED_CHAMPIONS,
    assign,
    get_assignment,
    unassign,
)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state_module, "_STATE_PATH", tmp_path / "cfd_bot_state.json")


def test_unassigned_champion_returns_none():
    assert get_assignment("champion_m30") is None


def test_assign_then_read_back():
    result = assign("champion_h4", "donchian_breakout", {"entry_window": 40}, "cleared TRAIN/TEST at H4", {"test_cagr": 0.12})
    assert result.strategy_name == "donchian_breakout"
    assert result.params == {"entry_window": 40}

    fetched = get_assignment("champion_h4")
    assert fetched.strategy_name == "donchian_breakout"
    assert fetched.reason == "cleared TRAIN/TEST at H4"


def test_reassignment_keeps_previous_in_history():
    assign("champion_d1", "ema_crossover", {}, "first pick", {})
    assign("champion_d1", "trend_pullback", {}, "ema_crossover decayed", {})

    champions = state_module.get_timeframe_champions()
    row = champions["champion_d1"]
    assert row["strategy_name"] == "trend_pullback"
    assert len(row["history"]) == 1
    assert row["history"][0]["strategy_name"] == "ema_crossover"


def test_unassign_clears_to_no_trade():
    assign("champion_m30", "mean_reversion", {}, "picked", {})
    unassign("champion_m30", "decay detected, no replacement validated yet")
    assert get_assignment("champion_m30") is None


def test_assign_rejects_unmanaged_account():
    with pytest.raises(ValueError):
        assign("core_h1", "ema_crossover", {}, "x", {})


def test_assign_rejects_unknown_strategy_name():
    with pytest.raises(ValueError):
        assign("champion_h4", "not_a_real_strategy", {}, "x", {})


def test_build_instantiates_the_real_strategy_class():
    from trading.cfd.strategy import EmaCrossoverStrategy

    result = assign("champion_h4", "ema_crossover", {}, "x", {})
    strategy = result.build()
    assert isinstance(strategy, EmaCrossoverStrategy)


def test_champion_specs_cover_every_managed_champion_plus_core_h1():
    assert set(CHAMPION_SPECS.keys()) == set(MANAGED_CHAMPIONS) | {"core_h1"}
    assert CHAMPION_SPECS["champion_m30"][0] == 1800
    assert CHAMPION_SPECS["champion_h4"][0] == 14400
    assert CHAMPION_SPECS["champion_d1"][0] == 86400

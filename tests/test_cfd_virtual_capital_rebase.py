import pytest

from trading.cfd import state


def test_rebase_demo_virtual_capital_resets_equity_derived_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.set_broker_baseline(3000.0)
    state.set_equity_tracking(2149.153, 6930.51)
    state.set_daily_risk_tracking("2026-09-21", 100.0, True)

    state.rebase_demo_virtual_capital(5218.64, 100.0)

    result = state.load_state()
    assert result["broker_baseline"] == 5218.64
    assert result["smoothed_equity"] == 100.0
    assert result["high_water_mark"] == 100.0
    assert result["daily_risk_tracking"] == {"date": None, "start_equity": None, "halted": False}


def test_normal_set_broker_baseline_remains_set_once(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.set_broker_baseline(3000.0)
    state.set_broker_baseline(5000.0)
    assert state.load_state()["broker_baseline"] == 3000.0

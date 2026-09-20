import json

from trading.cfd import state


def test_load_state_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    assert state.load_state() == {
        "paused": False, "pause_reason": "", "capital_floor": None, "initial_floor": None,
        "excluded_instruments": {}, "broker_baseline": None, "open_trades": {},
        "operating_mode": "normal", "operating_mode_reason": "",
        "paper_positions": {}, "paper_equity": {}, "paper_trade_counter": 0,
        "daily_risk_tracking": {"date": None, "start_equity": None, "halted": False},
        "pending_entries": {},
        "smoothed_equity": None,
        "high_water_mark": None,
    }


def test_set_paused_with_reason_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.set_paused(True, "macro risk")
    result = state.load_state()
    assert result["paused"] is True
    assert result["pause_reason"] == "macro risk"
    state.set_paused(False)
    assert state.load_state()["pause_reason"] == ""


def test_set_capital_floor_remembers_initial_floor_once(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.set_capital_floor(1000.0)
    assert state.load_state()["initial_floor"] == 1000.0
    state.set_capital_floor(1100.0)
    result = state.load_state()
    assert result["capital_floor"] == 1100.0
    assert result["initial_floor"] == 1000.0


def test_exclude_and_include_instrument_roundtrip(tmp_path, monkeypatch):
    # Deriv symbols are mixed-case and case-sensitive (frxXAUUSD) -- casing
    # must round-trip exactly, unlike the stock system's stock tickers.
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.exclude_instrument("frxXAUUSD", "spiking on Fed news")
    assert state.load_state()["excluded_instruments"] == {"frxXAUUSD": "spiking on Fed news"}
    state.include_instrument("frxXAUUSD")
    assert state.load_state()["excluded_instruments"] == {}


def test_set_operating_mode_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.set_operating_mode("defensive", "spread widening on gold")
    result = state.load_state()
    assert result["operating_mode"] == "defensive"
    assert result["operating_mode_reason"] == "spread widening on gold"


def test_set_operating_mode_rejects_unknown_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    import pytest

    with pytest.raises(ValueError):
        state.set_operating_mode("yolo")
    assert state.load_state()["operating_mode"] == "normal"  # unchanged


def test_next_paper_contract_id_is_negative_and_increments(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    first = state.next_paper_contract_id()
    second = state.next_paper_contract_id()
    assert first == -1
    assert second == -2


def test_paper_equity_defaults_then_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    assert state.get_paper_equity("ema_crossover@v1", default=100.0) == 100.0
    state.set_paper_equity("ema_crossover@v1", 110.5)
    assert state.get_paper_equity("ema_crossover@v1", default=100.0) == 110.5
    assert state.get_paper_equity("other@v1", default=100.0) == 100.0


def test_paper_position_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    assert state.get_paper_position("ema_crossover@v1", "frxXAUUSD") is None
    state.set_paper_position("ema_crossover@v1", "frxXAUUSD", {"side": "long"})
    assert state.get_paper_position("ema_crossover@v1", "frxXAUUSD") == {"side": "long"}
    popped = state.pop_paper_position("ema_crossover@v1", "frxXAUUSD")
    assert popped == {"side": "long"}
    assert state.get_paper_position("ema_crossover@v1", "frxXAUUSD") is None


def test_daily_risk_tracking_defaults_then_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    assert state.get_daily_risk_tracking() == {"date": None, "start_equity": None, "halted": False}
    state.set_daily_risk_tracking("2026-01-01", 100.0, True)
    assert state.get_daily_risk_tracking() == {"date": "2026-01-01", "start_equity": 100.0, "halted": True}


def test_set_broker_baseline_only_sets_once(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.set_broker_baseline(10000.0)
    assert state.load_state()["broker_baseline"] == 10000.0
    state.set_broker_baseline(9500.0)  # a later run must not move the anchor
    assert state.load_state()["broker_baseline"] == 10000.0


def test_record_open_trade_then_pop_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.record_open_trade(12345, {"instrument": "frxXAUUSD", "side": "long"})
    assert state.list_open_trades() == {"12345": {"instrument": "frxXAUUSD", "side": "long"}}

    popped = state.pop_open_trade(12345)
    assert popped == {"instrument": "frxXAUUSD", "side": "long"}
    assert state.list_open_trades() == {}


def test_pop_open_trade_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    assert state.pop_open_trade(999) is None


def test_state_file_is_valid_json(tmp_path, monkeypatch):
    path = tmp_path / "cfd_bot_state.json"
    monkeypatch.setattr(state, "_STATE_PATH", path)
    state.set_paused(True)
    assert json.loads(path.read_text())["paused"] is True


def test_load_state_does_not_leak_defaults_across_instances(tmp_path, monkeypatch):
    # Regression test for the mutable-default bug found in the stock
    # system's state.py: dict(_DEFAULTS) is a shallow copy, so mutating a
    # nested dict returned before any state file exists would otherwise
    # pollute the module-level default for every future fresh state.
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "a" / "cfd_bot_state.json")
    state.exclude_instrument("frxXAUUSD", "test")

    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "b" / "cfd_bot_state.json")
    assert state.load_state()["excluded_instruments"] == {}


def test_pending_entry_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.set_pending_entry("frxXAUUSD", {"legs": [{"side": "long", "leg": "runner"}]})
    assert state.get_pending_entries() == {"frxXAUUSD": {"legs": [{"side": "long", "leg": "runner"}]}}


def test_clear_pending_entry_removes_only_that_instrument(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.set_pending_entry("frxXAUUSD", {"legs": []})
    state.set_pending_entry("frxEURUSD", {"legs": []})
    state.clear_pending_entry("frxXAUUSD")
    assert state.get_pending_entries() == {"frxEURUSD": {"legs": []}}


def test_clear_pending_entry_on_missing_instrument_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.clear_pending_entry("frxXAUUSD")  # never set -- must not raise
    assert state.get_pending_entries() == {}


def test_equity_tracking_defaults_to_none(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    assert state.get_equity_tracking() == {"smoothed_equity": None, "high_water_mark": None}


def test_equity_tracking_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.set_equity_tracking(smoothed_equity=105.0, high_water_mark=110.0)
    assert state.get_equity_tracking() == {"smoothed_equity": 105.0, "high_water_mark": 110.0}

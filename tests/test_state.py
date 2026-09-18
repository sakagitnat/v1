import json

from trading.execution import state


def test_load_state_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    assert state.load_state() == {
        "paused": False, "pause_reason": "", "capital_floor": None, "initial_floor": None,
        "milestone_reached": False, "excluded_symbols": {},
    }


def test_set_paused_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "nested" / "bot_state.json")
    state.set_paused(True)
    assert state.load_state()["paused"] is True
    state.set_paused(False)
    assert state.load_state()["paused"] is False


def test_set_paused_with_reason_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    state.set_paused(True, "macro risk: unscheduled Fed announcement")
    assert state.load_state()["pause_reason"] == "macro risk: unscheduled Fed announcement"
    state.set_paused(False)
    assert state.load_state()["pause_reason"] == ""


def test_state_file_is_valid_json(tmp_path, monkeypatch):
    path = tmp_path / "bot_state.json"
    monkeypatch.setattr(state, "_STATE_PATH", path)
    state.set_paused(True)
    assert json.loads(path.read_text()) == {
        "paused": True, "pause_reason": "", "capital_floor": None, "initial_floor": None,
        "milestone_reached": False, "excluded_symbols": {},
    }


def test_set_capital_floor_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    state.set_capital_floor(100.0)
    assert state.load_state()["capital_floor"] == 100.0
    state.set_capital_floor(None)
    assert state.load_state()["capital_floor"] is None


def test_setting_capital_floor_preserves_paused_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    state.set_paused(True)
    state.set_capital_floor(100.0)
    result = state.load_state()
    assert result["paused"] is True
    assert result["capital_floor"] == 100.0


def test_loading_old_state_file_without_newer_keys(tmp_path, monkeypatch):
    path = tmp_path / "bot_state.json"
    path.write_text(json.dumps({"paused": False}))
    monkeypatch.setattr(state, "_STATE_PATH", path)
    assert state.load_state() == {
        "paused": False, "pause_reason": "", "capital_floor": None, "initial_floor": None,
        "milestone_reached": False, "excluded_symbols": {},
    }


def test_set_capital_floor_remembers_initial_floor_once(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    state.set_capital_floor(100.0)
    assert state.load_state()["initial_floor"] == 100.0
    state.set_capital_floor(115.0)  # e.g. ratcheted up
    result = state.load_state()
    assert result["capital_floor"] == 115.0
    assert result["initial_floor"] == 100.0  # unchanged


def test_clearing_capital_floor_leaves_initial_floor_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    state.set_capital_floor(100.0)
    state.set_capital_floor(None)
    result = state.load_state()
    assert result["capital_floor"] is None
    assert result["initial_floor"] == 100.0


def test_banked_profit_zero_without_a_floor():
    assert state.banked_profit({"capital_floor": None, "initial_floor": None}) == 0.0


def test_banked_profit_reflects_ratcheted_gain():
    assert state.banked_profit({"capital_floor": 115.0, "initial_floor": 100.0}) == 15.0


def test_set_milestone_reached_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    assert state.load_state()["milestone_reached"] is False
    state.set_milestone_reached(True)
    assert state.load_state()["milestone_reached"] is True
    state.set_milestone_reached(False)
    assert state.load_state()["milestone_reached"] is False


def test_exclude_symbol_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    state.exclude_symbol("aapl", "bad earnings surprise")
    result = state.load_state()
    assert result["excluded_symbols"] == {"AAPL": "bad earnings surprise"}


def test_exclude_symbol_without_reason_defaults_to_empty_string(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    state.exclude_symbol("TSLA")
    assert state.load_state()["excluded_symbols"] == {"TSLA": ""}


def test_include_symbol_removes_exclusion(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    state.exclude_symbol("AAPL", "news")
    state.exclude_symbol("TSLA", "news")
    state.include_symbol("aapl")
    assert state.load_state()["excluded_symbols"] == {"TSLA": "news"}


def test_include_symbol_not_excluded_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    state.include_symbol("AAPL")
    assert state.load_state()["excluded_symbols"] == {}

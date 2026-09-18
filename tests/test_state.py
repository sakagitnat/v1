import json

from trading.execution import state


def test_load_state_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    assert state.load_state() == {"paused": False, "capital_floor": None}


def test_set_paused_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "nested" / "bot_state.json")
    state.set_paused(True)
    assert state.load_state()["paused"] is True
    state.set_paused(False)
    assert state.load_state()["paused"] is False


def test_state_file_is_valid_json(tmp_path, monkeypatch):
    path = tmp_path / "bot_state.json"
    monkeypatch.setattr(state, "_STATE_PATH", path)
    state.set_paused(True)
    assert json.loads(path.read_text()) == {"paused": True, "capital_floor": None}


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


def test_loading_old_state_file_without_capital_floor_key(tmp_path, monkeypatch):
    path = tmp_path / "bot_state.json"
    path.write_text(json.dumps({"paused": False}))
    monkeypatch.setattr(state, "_STATE_PATH", path)
    assert state.load_state() == {"paused": False, "capital_floor": None}

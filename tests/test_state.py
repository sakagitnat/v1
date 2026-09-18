import json

from trading.execution import state


def test_load_state_defaults_to_not_paused(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "bot_state.json")
    assert state.load_state() == {"paused": False}


def test_set_paused_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "nested" / "bot_state.json")
    state.set_paused(True)
    assert state.load_state() == {"paused": True}
    state.set_paused(False)
    assert state.load_state() == {"paused": False}


def test_state_file_is_valid_json(tmp_path, monkeypatch):
    path = tmp_path / "bot_state.json"
    monkeypatch.setattr(state, "_STATE_PATH", path)
    state.set_paused(True)
    assert json.loads(path.read_text()) == {"paused": True}

import json

from trading.cfd import state


def test_load_state_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    assert state.load_state() == {
        "paused": False, "pause_reason": "", "capital_floor": None, "initial_floor": None,
        "excluded_instruments": {},
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
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    state.exclude_instrument("xau_usd", "spiking on Fed news")
    assert state.load_state()["excluded_instruments"] == {"XAU_USD": "spiking on Fed news"}
    state.include_instrument("XAU_USD")
    assert state.load_state()["excluded_instruments"] == {}


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
    state.exclude_instrument("XAU_USD", "test")

    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "b" / "cfd_bot_state.json")
    assert state.load_state()["excluded_instruments"] == {}

import json

from trading.cfd import mt5_state


def test_load_state_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(mt5_state, "_STATE_PATH", tmp_path / "mt5_bot_state.json")
    assert mt5_state.load_state() == {
        "paused": False, "pause_reason": "", "capital_floor": None, "initial_floor": None,
        "excluded_instruments": {},
    }


def test_set_paused_with_reason_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(mt5_state, "_STATE_PATH", tmp_path / "mt5_bot_state.json")
    mt5_state.set_paused(True, "PC going to sleep")
    result = mt5_state.load_state()
    assert result["paused"] is True
    assert result["pause_reason"] == "PC going to sleep"
    mt5_state.set_paused(False)
    assert mt5_state.load_state()["pause_reason"] == ""


def test_set_capital_floor_remembers_initial_floor_once(tmp_path, monkeypatch):
    monkeypatch.setattr(mt5_state, "_STATE_PATH", tmp_path / "mt5_bot_state.json")
    mt5_state.set_capital_floor(1000.0)
    assert mt5_state.load_state()["initial_floor"] == 1000.0
    mt5_state.set_capital_floor(1100.0)
    result = mt5_state.load_state()
    assert result["capital_floor"] == 1100.0
    assert result["initial_floor"] == 1000.0


def test_exclude_and_include_instrument_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mt5_state, "_STATE_PATH", tmp_path / "mt5_bot_state.json")
    mt5_state.exclude_instrument("XAUUSD", "spiking on Fed news")
    assert mt5_state.load_state()["excluded_instruments"] == {"XAUUSD": "spiking on Fed news"}
    mt5_state.include_instrument("XAUUSD")
    assert mt5_state.load_state()["excluded_instruments"] == {}


def test_state_file_is_valid_json(tmp_path, monkeypatch):
    path = tmp_path / "mt5_bot_state.json"
    monkeypatch.setattr(mt5_state, "_STATE_PATH", path)
    mt5_state.set_paused(True)
    assert json.loads(path.read_text())["paused"] is True


def test_load_state_does_not_leak_defaults_across_instances(tmp_path, monkeypatch):
    monkeypatch.setattr(mt5_state, "_STATE_PATH", tmp_path / "a" / "mt5_bot_state.json")
    mt5_state.exclude_instrument("XAUUSD", "test")

    monkeypatch.setattr(mt5_state, "_STATE_PATH", tmp_path / "b" / "mt5_bot_state.json")
    assert mt5_state.load_state()["excluded_instruments"] == {}


def test_append_trade_log_writes_one_json_line_per_call(tmp_path, monkeypatch):
    path = tmp_path / "mt5_trade_log.jsonl"
    monkeypatch.setattr(mt5_state, "_TRADE_LOG_PATH", path)
    mt5_state.append_trade_log({"event": "open", "symbol": "XAUUSD"})
    mt5_state.append_trade_log({"event": "close", "symbol": "XAUUSD", "pnl": 5.0})
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"event": "open", "symbol": "XAUUSD"}
    assert json.loads(lines[1]) == {"event": "close", "symbol": "XAUUSD", "pnl": 5.0}

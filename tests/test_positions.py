from trading.execution import positions


def test_load_positions_defaults_to_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(positions, "_POSITIONS_PATH", tmp_path / "positions.json")
    assert positions.load_positions() == {}


def test_record_open_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(positions, "_POSITIONS_PATH", tmp_path / "nested" / "positions.json")
    positions.record_open("AAPL", qty=0.5, stop_price=190.0, target_price=210.0)
    result = positions.load_positions()
    assert result == {"AAPL": {"qty": 0.5, "stop_price": 190.0, "target_price": 210.0}}


def test_record_close_removes_symbol(tmp_path, monkeypatch):
    monkeypatch.setattr(positions, "_POSITIONS_PATH", tmp_path / "positions.json")
    positions.record_open("AAPL", qty=0.5, stop_price=190.0, target_price=210.0)
    positions.record_open("MSFT", qty=0.2, stop_price=400.0, target_price=450.0)
    positions.record_close("AAPL")
    result = positions.load_positions()
    assert "AAPL" not in result
    assert "MSFT" in result


def test_record_close_on_untracked_symbol_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(positions, "_POSITIONS_PATH", tmp_path / "positions.json")
    positions.record_close("NOPE")
    assert positions.load_positions() == {}

from trading.cfd import state


def test_virtual_equity_tracks_demo_pnl_from_100_start(tmp_path, monkeypatch):
    state_path = tmp_path / "cfd_bot_state.json"
    monkeypatch.setattr(state, "_STATE_PATH", state_path)

    s = state.initialize_virtual_account(broker_equity=10_000.0, starting_capital=100.0)

    assert state.virtual_equity_for_broker_equity(s, 10_000.0) == 100.0
    assert state.virtual_equity_for_broker_equity(s, 10_025.0) == 125.0
    assert state.virtual_equity_for_broker_equity(s, 9_980.0) == 80.0


def test_virtual_account_does_not_rebase_on_later_runs(tmp_path, monkeypatch):
    state_path = tmp_path / "cfd_bot_state.json"
    monkeypatch.setattr(state, "_STATE_PATH", state_path)

    first = state.initialize_virtual_account(broker_equity=10_000.0, starting_capital=100.0)
    second = state.initialize_virtual_account(broker_equity=10_040.0, starting_capital=100.0)

    assert first["broker_equity_baseline"] == 10_000.0
    assert second["broker_equity_baseline"] == 10_000.0
    assert state.virtual_equity_for_broker_equity(second, 10_040.0) == 140.0

from trading.cfd import state
from trading.cfd.virtual_accounts import (
    ACTIVE_DEMO,
    PAPER,
    SHADOW,
    account_for_strategy,
    ensure_virtual_accounts,
    record_virtual_close,
)


def test_virtual_account_lab_seeds_separate_100_dollar_ledgers(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    accounts = ensure_virtual_accounts()
    assert accounts["core_h1"]["starting_equity"] == 100.0
    assert accounts["core_h1"]["equity"] == 100.0
    assert accounts["core_h1"]["execution_tier"] == ACTIVE_DEMO
    assert accounts["breakout_h1"]["execution_tier"] == PAPER
    assert accounts["intraday_m15"]["execution_tier"] == SHADOW
    assert accounts["intraday_m5"]["entry_timeframe"] == "M5"
    assert accounts["scalp_m1"]["entry_timeframe"] == "M1"


def test_virtual_account_seed_does_not_overwrite_results(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    ensure_virtual_accounts()
    accounts = state.get_virtual_accounts()
    accounts["intraday_m15"]["equity"] = 93.5
    state.set_virtual_accounts(accounts)
    ensure_virtual_accounts()
    assert state.get_virtual_accounts()["intraday_m15"]["equity"] == 93.5


def test_record_virtual_close_updates_only_one_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    ensure_virtual_accounts()
    record_virtual_close("core_h1", 2.5)
    accounts = state.get_virtual_accounts()
    assert accounts["core_h1"]["equity"] == 102.5
    assert accounts["core_h1"]["realized_pnl"] == 2.5
    assert accounts["core_h1"]["wins"] == 1
    assert accounts["intraday_m15"]["equity"] == 100.0


def test_strategy_maps_to_account():
    assert account_for_strategy("ema_crossover@v1") == "core_h1"
    assert account_for_strategy("donchian_breakout@v2") == "breakout_h1"
    assert account_for_strategy("unknown@v1") is None

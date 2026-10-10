import pytest

from trading.cfd import state, trade_log
from trading.cfd.trade_log import TradeRecord
from trading.cfd.virtual_accounts import (
    ACTIVE_DEMO,
    PAPER,
    SHADOW,
    account_for_strategy,
    commit_trade_settlement,
    ensure_virtual_accounts,
    flush_trade_settlements,
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


def _record(contract_id, pnl, account_id="core_h1", **overrides):
    fields = dict(
        contract_id=contract_id, instrument="frxXAUUSD", strategy="ema_crossover@v1", side="long",
        entry_time="2026-01-01T00:00:00Z", exit_time="2026-01-01T01:00:00Z", entry_price=2000.0,
        stake=10.0, risk_amount=1.0, pnl=pnl, virtual_account_id=account_id,
    )
    fields.update(overrides)
    return TradeRecord(**fields)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    monkeypatch.setattr(trade_log, "_LOG_PATH", tmp_path / "cfd_trades.jsonl")


def test_commit_trade_settlement_applies_pnl_and_pops_open_trade(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ensure_virtual_accounts()
    state.record_open_trade(42, {"instrument": "frxXAUUSD", "virtual_account_id": "core_h1"})

    row = commit_trade_settlement(_record(42, 4.5))

    assert row["equity"] == 104.5
    assert row["closed_trades"] == 1
    assert row["wins"] == 1
    assert "42" not in state.list_open_trades()
    trades = trade_log.load_trades()
    assert len(trades) == 1
    assert trades[0]["contract_id"] == 42
    assert trades[0]["pnl"] == 4.5


def test_commit_trade_settlement_is_idempotent_for_the_same_contract_id(tmp_path, monkeypatch):
    """The regression case for the production bug: a retry of the exact
    same settlement (e.g. a next run re-discovering a contract it thinks
    still needs closing) must never apply the same pnl twice."""
    _isolate(tmp_path, monkeypatch)
    ensure_virtual_accounts()
    state.record_open_trade(42, {"instrument": "frxXAUUSD", "virtual_account_id": "core_h1"})

    commit_trade_settlement(_record(42, 4.5))
    second = commit_trade_settlement(_record(42, 4.5))

    assert second is None
    assert state.load_state()["virtual_accounts"]["core_h1"]["equity"] == 104.5  # not 109.0
    assert len(trade_log.load_trades()) == 1  # not duplicated either


def test_commit_trade_settlement_rejects_conflicting_evidence_for_the_same_contract_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ensure_virtual_accounts()
    state.record_open_trade(42, {"instrument": "frxXAUUSD", "virtual_account_id": "core_h1"})
    commit_trade_settlement(_record(42, 4.5))

    with pytest.raises(RuntimeError, match="Conflicting settlement evidence"):
        commit_trade_settlement(_record(42, -1.0))

    # The original, correct settlement must be left untouched.
    assert state.load_state()["virtual_accounts"]["core_h1"]["equity"] == 104.5


def test_commit_trade_settlement_skips_equity_when_pnl_is_unattributable(tmp_path, monkeypatch):
    """pnl=None (never coerced to 0.0 -- see TradeRecord.pnl's docstring)
    must still be logged and popped, but must never touch equity."""
    _isolate(tmp_path, monkeypatch)
    ensure_virtual_accounts()
    state.record_open_trade(42, {"instrument": "frxXAUUSD", "virtual_account_id": "core_h1"})

    row = commit_trade_settlement(_record(42, None))

    assert row is None
    assert state.load_state()["virtual_accounts"]["core_h1"]["equity"] == 100.0
    assert "42" not in state.list_open_trades()
    assert len(trade_log.load_trades()) == 1


def test_flush_trade_settlements_is_a_no_op_once_the_log_already_has_the_contract(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ensure_virtual_accounts()
    state.record_open_trade(42, {"instrument": "frxXAUUSD", "virtual_account_id": "core_h1"})
    commit_trade_settlement(_record(42, 4.5))

    flush_trade_settlements()  # must not re-append or re-apply anything
    flush_trade_settlements()

    assert len(trade_log.load_trades()) == 1
    assert state.load_state()["virtual_accounts"]["core_h1"]["equity"] == 104.5

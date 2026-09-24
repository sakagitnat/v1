import asyncio
from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest

from trading.cfd import champion_scheduler, state, timeframe_champion, trade_log, virtual_accounts
from trading.strategy.base import Action, Signal


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    monkeypatch.setattr(trade_log, "_LOG_PATH", tmp_path / "cfd_trades.jsonl")
    monkeypatch.setattr(virtual_accounts, "RUIN_LOG_PATH", tmp_path / "cfd_virtual_account_ruin_log.jsonl")
    monkeypatch.setattr(champion_scheduler.settings, "cfd_instruments", ["frxXAUUSD"])


def _bars(n=200):
    return pd.DataFrame(
        {"open": [2000.0] * n, "high": [2001.0] * n, "low": [1999.0] * n, "close": [2000.0] * n, "atr": [2.0] * n},
        index=pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"),
    )


def _broker(**overrides):
    broker = Mock()
    broker.open_contract_ids = AsyncMock(return_value=set())
    broker.get_candles = AsyncMock(return_value=_bars())
    broker.settled_profit = AsyncMock()
    broker.close_position = AsyncMock()
    broker.submit_multiplier_order = AsyncMock(return_value={"buy": {"contract_id": 999}})
    for key, value in overrides.items():
        setattr(broker, key, value)
    return broker


def _stub_strategy(monkeypatch, signal: Signal):
    strategy = Mock()
    strategy.prepare.return_value = _bars()
    strategy.signal_for_row.return_value = signal
    monkeypatch.setattr(champion_scheduler, "_build_strategy", lambda name, params: strategy)
    return strategy


def test_unassigned_champion_is_no_trade_and_never_calls_the_broker_to_submit():
    broker = _broker()
    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))
    assert summary == [{"instrument": "frxXAUUSD", "outcome": "NO_TRADE", "reason": "champion_m30: unassigned (no validated strategy for this timeframe yet)"}]
    broker.submit_multiplier_order.assert_not_awaited()


def test_hold_signal_is_no_trade(monkeypatch):
    timeframe_champion.assign("champion_m30", "ema_crossover", {}, "test", {})
    broker = _broker()
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.HOLD, 2000.0, reason="no crossover"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert summary == [{"instrument": "frxXAUUSD", "outcome": "NO_TRADE", "reason": "no crossover"}]
    broker.submit_multiplier_order.assert_not_awaited()


def test_buy_signal_opens_a_position_tagged_with_the_champion_account(monkeypatch):
    timeframe_champion.assign("champion_m30", "ema_crossover", {}, "test", {})
    broker = _broker()
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.BUY, 2000.0, stop_price=1990.0, take_profit_price=2020.0, reason="crossed up"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert summary[0]["outcome"] == "TRADE"
    broker.submit_multiplier_order.assert_awaited_once()
    open_trades = state.list_open_trades()
    assert len(open_trades) == 1
    meta = list(open_trades.values())[0]
    assert meta["virtual_account_id"] == "champion_m30"
    assert meta["side"] == "long"
    assert meta["strategy"] == "ema_crossover"


def test_stake_computed_as_zero_is_no_trade(monkeypatch):
    timeframe_champion.assign("champion_m30", "ema_crossover", {}, "test", {})
    broker = _broker()
    # zero stop distance -> stake_and_limits degenerates to (0, 0, 0)
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.BUY, 2000.0, stop_price=2000.0, take_profit_price=2020.0, reason="x"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert summary[0]["outcome"] == "NO_TRADE"
    broker.submit_multiplier_order.assert_not_awaited()


def test_position_still_open_with_no_signal_exit_is_left_alone(monkeypatch):
    state.record_open_trade(42, {
        "instrument": "frxXAUUSD", "strategy": "ema_crossover", "side": "long",
        "entry_time": "2026-01-01T00:00:00Z", "entry_price": 2000.0, "stake": 10.0,
        "risk_amount": 1.0, "equity_before": 100.0, "virtual_account_id": "champion_m30",
    })
    broker = _broker(open_contract_ids=AsyncMock(return_value={42}))
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.HOLD, 2000.0, reason="still trending"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert summary == [{"instrument": "frxXAUUSD", "outcome": "NO_TRADE", "reason": "champion_m30: position still open"}]
    assert "42" in state.list_open_trades()
    broker.close_position.assert_not_awaited()
    broker.settled_profit.assert_not_awaited()


def test_position_closed_externally_is_reconciled_via_settled_profit(monkeypatch):
    state.record_open_trade(42, {
        "instrument": "frxXAUUSD", "strategy": "ema_crossover", "side": "long",
        "entry_time": "2026-01-01T00:00:00Z", "entry_price": 2000.0, "stake": 10.0,
        "risk_amount": 1.0, "equity_before": 100.0, "virtual_account_id": "champion_m30",
    })
    virtual_accounts.ensure_virtual_accounts()
    broker = _broker(open_contract_ids=AsyncMock(return_value=set()))
    broker.settled_profit = AsyncMock(return_value=4.5)
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.HOLD, 2000.0, reason="n/a"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert summary == [{"instrument": "frxXAUUSD", "outcome": "TRADE", "reason": "champion_m30: closed, pnl=+4.50"}]
    assert state.list_open_trades() == {}
    ledger = virtual_accounts.ensure_virtual_accounts()["champion_m30"]
    assert ledger["equity"] == 104.5
    assert ledger["realized_pnl"] == 4.5


def test_signal_exit_closes_the_position_via_the_broker(monkeypatch):
    state.record_open_trade(42, {
        "instrument": "frxXAUUSD", "strategy": "ema_crossover", "side": "long",
        "entry_time": "2026-01-01T00:00:00Z", "entry_price": 2000.0, "stake": 10.0,
        "risk_amount": 1.0, "equity_before": 100.0, "virtual_account_id": "champion_m30",
    })
    broker = _broker(open_contract_ids=AsyncMock(return_value={42}))
    broker.settled_profit = AsyncMock(return_value=-1.0)
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.SELL, 2000.0, reason="crossed down"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    broker.close_position.assert_awaited_once_with(42)
    assert summary == [{"instrument": "frxXAUUSD", "outcome": "TRADE", "reason": "champion_m30: closed, pnl=-1.00"}]


def test_managed_champions_are_evaluated_in_run_champions():
    broker = _broker()
    summary = asyncio.run(champion_scheduler.run_champions(broker))
    # all three unassigned by default -- one NO_TRADE entry per (champion, instrument)
    assert len(summary) == len(timeframe_champion.MANAGED_CHAMPIONS)
    assert all(row["outcome"] == "NO_TRADE" for row in summary)

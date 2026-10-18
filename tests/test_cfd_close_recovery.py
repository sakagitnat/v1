import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest

from trading.cfd import scheduler, state
from trading.strategy.base import Action, Signal


@pytest.mark.parametrize("failure_stage", ["sell", "balance", "still_open", "settlement"])
def test_failed_close_preserves_position_metadata(tmp_path, monkeypatch, failure_stage):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "state.json")
    state.set_broker_baseline(10000)
    meta = dict(instrument="frxXAUUSD", strategy="test@v1", side="long",
                stake=10, risk_amount=1, multiplier=20, entry_price=2000,
                equity_before=100, entry_time="2026-01-01T00:00:00Z")
    state.record_open_trade(42, meta)
    monkeypatch.setattr(scheduler.settings, "cfd_instruments", ["frxXAUUSD"])
    bars = pd.DataFrame({"open": [2000.] * 200, "high": [2001.] * 200,
                         "low": [1999.] * 200, "close": [2000.] * 200,
                         "atr": [2.] * 200},
                        index=pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC"))
    strategy = Mock()
    strategy.prepare.return_value = bars
    strategy.signal_for_row.return_value = Signal("frxXAUUSD", Action.SELL, 2000, reason="test exit")
    entry = SimpleNamespace(name="test", version="v1", build=lambda: strategy)
    broker = Mock()
    broker.connect = AsyncMock(return_value={"account_type": "demo"})
    broker.account_equity = AsyncMock(side_effect=[9990., ConnectionError("test disconnect")] if failure_stage == "balance" else [9990., 10000.])
    broker.open_contract_ids = AsyncMock(side_effect=[{42}, {42} if failure_stage == "still_open" else set()])
    broker.open_positions_list = AsyncMock(return_value=[{"contract_id": 42, "instrument": "frxXAUUSD", "side": "long"}])
    broker.get_candles = AsyncMock(return_value=bars)
    broker.close_position = AsyncMock(side_effect=ConnectionError("test disconnect") if failure_stage == "sell" else None)
    broker.close = AsyncMock()
    broker.settled_profit = AsyncMock(side_effect=RuntimeError("settlement unavailable"))
    monkeypatch.setattr(scheduler, "DerivBroker", lambda: broker)
    monkeypatch.setattr(scheduler, "load_trades", lambda: [])
    monkeypatch.setattr(scheduler, "run_autonomous_demotion", lambda _: [])
    monkeypatch.setattr(scheduler, "list_by_state", lambda _: [entry])
    monkeypatch.setattr(scheduler, "compute_allocations", lambda *args: {})
    monkeypatch.setattr(scheduler, "collect_lab_observations", AsyncMock(return_value=[]))
    monkeypatch.setattr(scheduler, "_resolve_exit_strategy_entry", lambda _: entry)
    monkeypatch.setattr(scheduler, "run_paper_trading", lambda *args: None)
    with pytest.raises((ConnectionError, RuntimeError)):
        asyncio.run(scheduler.run_once())
    assert state.list_open_trades()["42"] == meta
    broker.close_position.assert_awaited_once_with(42)
    broker.close.assert_awaited_once()

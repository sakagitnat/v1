import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from trading.cfd import quota, state, trade_log
from trading.config import settings


class Broker:
    def __init__(self):
        self.opened = set()
        self.buys = 0
        self.fail_sell = False
    async def connect(self):
        return {"account_type": "demo", "currency": "USD"}
    async def close(self):
        pass
    async def list_active_symbols(self):
        return [{"underlying_symbol": "frxXAUUSD", "exchange_is_open": 1}]
    async def open_contract_ids(self):
        return self.opened.copy()
    async def account_equity(self):
        return 10000
    async def get_ticks(self, symbol, count):
        return pd.DataFrame({"price": [2000, 2001]}, index=pd.date_range("2026-09-23T12:04:58Z", periods=2, freq="s"))
    async def get_candles(self, symbol, granularity, count):
        end = pd.Timestamp("2026-09-23T12:05:00Z").floor(f"{granularity}s")
        return pd.DataFrame({"close": range(2000, 2080)}, index=pd.date_range(end=end, periods=80, freq=f"{granularity}s"))
    async def submit_multiplier_order(self, *args):
        self.buys += 1
        self.opened.add(self.buys)
        return {"buy": {"contract_id": self.buys, "buy_price": 1}}
    async def close_position(self, cid):
        if self.fail_sell:
            raise TimeoutError("ambiguous sell")
        self.opened.remove(cid)
        return {"sell": {"contract_id": cid, "sold_for": "0.99"}}
    async def settled_profit(self, cid):
        return -0.01


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(trade_log, "_LOG_PATH", tmp_path / "trades.jsonl")
    monkeypatch.setattr(quota, "LOG_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(quota, "now", lambda: datetime(2026, 9, 23, 12, 5, tzinfo=timezone.utc))
    monkeypatch.setattr(quota.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(settings, "cfd_allow_live_trading", False)
    monkeypatch.setattr(settings, "cfd_instruments", ["frxXAUUSD"])
    state.set_broker_baseline(10000)
    broker = Broker()
    monkeypatch.setattr(quota, "DerivBroker", lambda: broker)
    return broker


def test_all_four_windows_close_and_same_window_rerun_does_not_buy(setup):
    result = asyncio.run(quota.run_quotas())
    assert [r["outcome"] for r in result] == ["CLOSED"] * 4
    assert setup.buys == 4
    assert not setup.opened
    s = state.load_state()
    assert not s["open_trades"] and not s["pending_entries"]
    assert len(s["quota_settlements"]) == 4
    assert all(s["virtual_accounts"][aid]["equity"] == 99.99 for aid in quota.SPECS)
    assert len(trade_log.load_trades()) == 4
    assert all(r["outcome"] == "ALREADY_COMPLETED" for r in asyncio.run(quota.run_quotas()))
    assert setup.buys == 4


def test_sell_timeout_preserves_position_and_recovery_does_not_rebuy(setup):
    setup.fail_sell = True
    with pytest.raises(TimeoutError):
        asyncio.run(quota.run_quotas())
    assert setup.buys == 1 and "1" in state.list_open_trades()
    setup.fail_sell = False
    asyncio.run(quota.run_quotas())
    assert setup.buys == 4  # recovery closes old first account, adds only three
    assert len(trade_log.load_trades()) == 4


def test_outbox_replay_does_not_double_credit_after_log_failure(setup, monkeypatch):
    original = quota.record_trade
    monkeypatch.setattr(quota, "record_trade", lambda _: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        asyncio.run(quota.run_quotas())
    assert state.load_state()["virtual_accounts"]["quota_30m_forward"]["equity"] == 99.99
    monkeypatch.setattr(quota, "record_trade", original)
    asyncio.run(quota.run_quotas())
    assert setup.buys == 4
    assert len(trade_log.load_trades()) == 4
    assert state.load_state()["virtual_accounts"]["quota_30m_forward"]["closed_trades"] == 1


def test_pending_buy_blocks_new_orders(setup):
    state.set_pending_entry("frxXAUUSD", {"quota_intent": True, "legs": []})
    assert all(r["outcome"] == "RECOVERY_OR_PAUSE_BLOCKED" for r in asyncio.run(quota.run_quotas()))
    assert setup.buys == 0


def test_foreign_exposure_blocks_orders(setup):
    setup.opened.add(999)
    assert all(r["outcome"] == "RECONCILIATION_REQUIRED" for r in asyncio.run(quota.run_quotas()))
    assert setup.buys == 0


def test_demo_guard(setup, monkeypatch):
    monkeypatch.setattr(settings, "cfd_allow_live_trading", True)
    with pytest.raises(RuntimeError, match="DEMO"):
        asyncio.run(quota.run_quotas())
    assert setup.buys == 0


@pytest.mark.parametrize("sold_for", [None, True, "NaN", "inf", -1])
def test_invalid_sale_proceeds_never_become_profit(sold_for):
    with pytest.raises(RuntimeError):
        quota.profit_from_sale({"sell": {"contract_id": 42, "sold_for": sold_for}}, 42, 1)


def test_actual_deriv_sold_for_response_regression():
    assert quota.profit_from_sale({"sell": {"contract_id": 14051102839, "sold_for": .99}}, 14051102839, 1) == -.01


def test_failed_atomic_replace_keeps_old_state(setup, monkeypatch):
    before = state.load_state()
    monkeypatch.setattr(state.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        state.set_paused(True)
    assert state.load_state() == before

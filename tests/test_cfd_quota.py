import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from trading.cfd import quota, state, trade_log
from trading.cfd.broker import DerivRequestError
from trading.config import settings


class Broker:
    def __init__(self):
        self.opened = set()
        self.buys = 0
        self.fail_sell = False
        self.fail_order_stage = None  # None | "proposal" | "buy"
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
        if self.fail_order_stage is not None:
            raise DerivRequestError(self.fail_order_stage, "simulated failure")
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
    monkeypatch.setattr(settings, "cfd_max_open_positions", 5)
    state.set_broker_baseline(10000)
    broker = Broker()
    monkeypatch.setattr(quota, "DerivBroker", lambda: broker)
    return broker


def expire_positions():
    for cid, meta in state.list_open_trades().items():
        meta["close_at"] = 1
        state.record_open_trade(int(cid), meta)


def test_timeframe_positions_survive_cycles_then_settle_once(setup):
    result = asyncio.run(quota.run_quotas())
    assert [r["outcome"] for r in result] == ["OPENED"] * 4
    assert {m["entry_timeframe"] for m in state.list_open_trades().values()} == {"M30", "H1", "H4", "D1"}
    assert all(r["outcome"] == "HOLDING" for r in asyncio.run(quota.run_quotas()))
    assert setup.buys == 4
    expire_positions()
    asyncio.run(quota.run_quotas())
    assert not setup.opened
    assert len(trade_log.load_trades()) == 4
    assert all(state.load_state()["virtual_accounts"][aid]["equity"] == 99.99 for aid in quota.SPECS)
    assert all(r["outcome"] == "ALREADY_COMPLETED" for r in asyncio.run(quota.run_quotas()))
    assert setup.buys == 4


def test_sell_timeout_preserves_position_and_recovery_does_not_rebuy(setup):
    asyncio.run(quota.run_quotas())
    expire_positions()
    setup.fail_sell = True
    with pytest.raises(TimeoutError):
        asyncio.run(quota.run_quotas())
    assert "1" in state.list_open_trades()
    setup.fail_sell = False
    asyncio.run(quota.run_quotas())
    assert setup.buys == 4
    assert len(trade_log.load_trades()) == 4


def test_outbox_replay_does_not_double_credit_after_log_failure(setup, monkeypatch):
    asyncio.run(quota.run_quotas())
    expire_positions()
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


def test_price_request_failure_clears_its_own_pending_and_does_not_block_other_accounts(setup):
    """Regression test for the production incident: a proposal-stage
    rejection (Deriv refuses before any buy is even attempted, e.g. the
    symbol's market is closed) must never leave a stuck pending entry --
    that stuck entry is exactly what blocked all four quota accounts
    (RECOVERY_OR_PAUSE_BLOCKED, see the test above) for hours."""
    setup.fail_order_stage = "proposal"
    result = asyncio.run(quota.run_quotas())
    assert [r["outcome"] for r in result] == ["PRICE_REQUEST_FAILED"] * 4
    assert setup.buys == 0
    assert state.get_pending_entries() == {}

    # And, critically, it must not have left anything behind to block a
    # later run either -- this is the actual production symptom.
    setup.fail_order_stage = None
    result = asyncio.run(quota.run_quotas())
    assert [r["outcome"] for r in result] == ["OPENED"] * 4


def test_buy_result_unknown_leaves_pending_entry_for_reconciliation(setup):
    """A buy-stage failure is genuinely ambiguous -- Deriv may have
    processed the order before the error/timeout reached us -- so unlike a
    proposal-stage failure, the pending entry must NOT be cleared here."""
    setup.fail_order_stage = "buy"
    result = asyncio.run(quota.run_quotas())
    assert result[0]["outcome"] == "BUY_RESULT_UNKNOWN"
    assert setup.buys == 0
    # Only the first account gets as far as attempting an order this run --
    # its still-unresolved pending entry blocks the other three up front,
    # same as test_pending_buy_blocks_new_orders. That's the deliberately
    # conservative existing behavior; this test is about the pending entry
    # itself surviving a buy-stage failure, not the blocking rule per se.
    assert list(state.get_pending_entries().keys()) == ["frxXAUUSD"]


def test_thirty_minute_deadline_closes_without_closing_longer_horizons(setup, monkeypatch):
    asyncio.run(quota.run_quotas())
    monkeypatch.setattr(quota, "now", lambda: datetime(2026, 9, 23, 12, 28, tzinfo=timezone.utc))
    result = asyncio.run(quota.run_quotas())
    assert result[0]["outcome"] == "CLOSED"
    assert result[0]["account"] == "quota_30m_forward"
    assert len(setup.opened) == 3
    assert setup.buys == 4


def test_broker_stop_is_accounted_before_time_deadline(setup):
    asyncio.run(quota.run_quotas())
    setup.opened.remove(1)
    asyncio.run(quota.run_quotas())
    assert setup.buys == 4
    assert state.load_state()["virtual_accounts"]["quota_30m_forward"]["closed_trades"] == 1


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

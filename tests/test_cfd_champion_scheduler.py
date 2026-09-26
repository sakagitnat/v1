import asyncio
from datetime import datetime, timezone
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
    broker.open_positions_list = AsyncMock(return_value=[])
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
    broker = _broker(open_positions_list=AsyncMock(return_value=[{"contract_id": 42, "instrument": "frxXAUUSD"}]))
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
    broker = _broker(open_positions_list=AsyncMock(return_value=[]))
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
    broker = _broker(open_positions_list=AsyncMock(return_value=[{"contract_id": 42, "instrument": "frxXAUUSD"}]))
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


# 2026-09-24 review fixes -- P1: a paused bot state and an excluded
# instrument must gate champions the same way they already gate
# run_once(); v1 of this module checked neither.

def test_paused_bot_blocks_the_champion_entirely(monkeypatch):
    timeframe_champion.assign("champion_m30", "ema_crossover", {}, "test", {})
    state.set_paused(True, "testing")
    broker = _broker()
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.BUY, 2000.0, stop_price=1990.0, take_profit_price=2020.0, reason="crossed up"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert summary == [{"instrument": "*", "outcome": "NO_TRADE", "reason": "champion_m30: bot paused"}]
    broker.get_candles.assert_not_awaited()
    broker.submit_multiplier_order.assert_not_awaited()


def test_excluded_instrument_blocks_a_new_entry(monkeypatch):
    timeframe_champion.assign("champion_m30", "ema_crossover", {}, "test", {})
    state.exclude_instrument("frxXAUUSD", "spiking on Fed news")
    broker = _broker()
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.BUY, 2000.0, stop_price=1990.0, take_profit_price=2020.0, reason="crossed up"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert summary == [{"instrument": "frxXAUUSD", "outcome": "NO_TRADE", "reason": "champion_m30: excluded (spiking on Fed news)"}]
    broker.submit_multiplier_order.assert_not_awaited()


def test_excluded_instrument_does_not_block_managing_an_already_open_position(monkeypatch):
    # Exclusion protects against taking on NEW risk -- it must not maroon
    # a position this champion already holds, whose exit is Deriv's own
    # stop_loss/take_profit or the strategy's own signal exit either way.
    state.record_open_trade(42, {
        "instrument": "frxXAUUSD", "strategy": "ema_crossover", "side": "long",
        "entry_time": "2026-01-01T00:00:00Z", "entry_price": 2000.0, "stake": 10.0,
        "risk_amount": 1.0, "equity_before": 100.0, "virtual_account_id": "champion_m30",
    })
    state.exclude_instrument("frxXAUUSD", "spiking on Fed news")
    virtual_accounts.ensure_virtual_accounts()
    broker = _broker(open_positions_list=AsyncMock(return_value=[]))
    broker.settled_profit = AsyncMock(return_value=4.5)
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.HOLD, 2000.0, reason="n/a"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert summary == [{"instrument": "frxXAUUSD", "outcome": "TRADE", "reason": "champion_m30: closed, pnl=+4.50"}]


# 2026-09-24 review fix -- P1: CfdRiskManager.__post_init__ now recomputes
# halted from equity vs daily_start_equity itself (trading.cfd.risk), so
# an already-breached day can't be masked by a stale persisted flag --
# covered directly in tests/test_cfd_risk.py. This is the champion-level
# integration check that the recomputed halt actually blocks an entry.

def test_already_breached_daily_loss_blocks_entry_even_with_a_stale_halted_flag(monkeypatch):
    timeframe_champion.assign("champion_m30", "ema_crossover", {}, "test", {})
    today = datetime.now(timezone.utc).date().isoformat()
    accounts = virtual_accounts.ensure_virtual_accounts()
    accounts["champion_m30"]["equity"] = 96.0  # 4% down today, over the 3% cap
    state.set_virtual_accounts(accounts)
    state.set_champion_daily_risk_tracking("champion_m30", today, 100.0, False)  # flag never got updated
    broker = _broker()
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.BUY, 2000.0, stop_price=1990.0, take_profit_price=2020.0, reason="crossed up"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert summary[0]["outcome"] == "NO_TRADE"
    broker.submit_multiplier_order.assert_not_awaited()


# 2026-09-24 review fix -- P1: a pending-entry marker is now recorded
# before order submission and cleared after, in its own
# champion_pending_entries namespace (never run_once()'s pending_entries
# -- see state.get_champion_pending_entries' docstring for why).

def test_pending_entry_is_set_before_submit_and_cleared_after_it_commits(monkeypatch):
    timeframe_champion.assign("champion_m30", "ema_crossover", {}, "test", {})
    broker = _broker()
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.BUY, 2000.0, stop_price=1990.0, take_profit_price=2020.0, reason="crossed up"))

    seen_during_submit = {}

    async def submit_and_capture(*args, **kwargs):
        seen_during_submit.update(state.get_champion_pending_entries())
        return {"buy": {"contract_id": 999}}

    broker.submit_multiplier_order = AsyncMock(side_effect=submit_and_capture)

    asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert "champion_m30:frxXAUUSD" in seen_during_submit
    assert state.get_champion_pending_entries() == {}


def test_pending_entry_survives_a_missing_contract_id_for_next_runs_reconciliation(monkeypatch):
    timeframe_champion.assign("champion_m30", "ema_crossover", {}, "test", {})
    broker = _broker(submit_multiplier_order=AsyncMock(return_value={"buy": {}}))  # no contract_id
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.BUY, 2000.0, stop_price=1990.0, take_profit_price=2020.0, reason="crossed up"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert summary[0]["outcome"] == "ERROR"
    assert "champion_m30:frxXAUUSD" in state.get_champion_pending_entries()


def test_pending_entry_is_adopted_if_exactly_one_untracked_contract_matches(monkeypatch):
    timeframe_champion.assign("champion_m30", "ema_crossover", {}, "test", {})
    state.set_champion_pending_entry("champion_m30:frxXAUUSD", {
        "instrument": "frxXAUUSD", "strategy": "ema_crossover", "strategy_params": {}, "side": "long",
        "entry_time": "2026-01-01T00:00:00Z", "entry_price": 2000.0, "stake": 10.0, "risk_amount": 1.0,
        "equity_before": 100.0, "virtual_account_id": "champion_m30", "horizon": "champion",
    })
    broker = _broker(open_positions_list=AsyncMock(return_value=[{"contract_id": 77, "instrument": "frxXAUUSD"}]))
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.HOLD, 2000.0, reason="n/a"))

    summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    open_trades = state.list_open_trades()
    assert "77" in open_trades
    assert open_trades["77"]["virtual_account_id"] == "champion_m30"
    assert state.get_champion_pending_entries() == {}
    assert summary == [{"instrument": "frxXAUUSD", "outcome": "NO_TRADE", "reason": "champion_m30: position still open"}]


def test_pending_entry_is_dropped_not_chased_forever_when_unresolvable(monkeypatch):
    timeframe_champion.assign("champion_m30", "ema_crossover", {}, "test", {})
    state.set_champion_pending_entry("champion_m30:frxXAUUSD", {
        "instrument": "frxXAUUSD", "strategy": "ema_crossover", "strategy_params": {}, "side": "long",
        "entry_time": "2026-01-01T00:00:00Z", "entry_price": 2000.0, "stake": 10.0, "risk_amount": 1.0,
        "equity_before": 100.0, "virtual_account_id": "champion_m30", "horizon": "champion",
    })
    broker = _broker(open_positions_list=AsyncMock(return_value=[]))  # order never actually went through
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.HOLD, 2000.0, reason="n/a"))

    asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    assert state.get_champion_pending_entries() == {}
    assert state.list_open_trades() == {}


def test_champion_pending_entries_are_never_touched_by_run_once(monkeypatch):
    # The whole point of the separate champion_pending_entries namespace:
    # run_once() unconditionally sweeps every entry in "pending_entries"
    # it doesn't adopt, at the end of every single run. If champions
    # shared that key, run_once() -- which always runs first in the same
    # process, see scripts/run_cfd_trading.py's run_normal() -- would
    # wipe a champion's still-unresolved marker before the champion's own
    # reconciliation this same tick ever saw it.
    state.set_champion_pending_entry("champion_m30:frxXAUUSD", {"instrument": "frxXAUUSD"})
    assert state.get_pending_entries() == {}
    assert "champion_m30:frxXAUUSD" in state.get_champion_pending_entries()


# 2026-09-25 review fix -- P1 superseded: the original fix here (record
# durable records before popping open_trades) prevented LOSING the only
# local record on a partial failure, but it didn't prevent DOUBLE-COUNTING
# it either -- if record_virtual_close succeeded but record_trade then
# raised, the contract stayed tracked open for a next-run retry, which
# walked through record_virtual_close a second time for the same pnl
# (confirmed reproducible: one $4.50 win applied twice took $100 to $109).
# commit_trade_settlement (trading.cfd.virtual_accounts) replaces the
# three separate calls with one atomic settlement: equity + a
# contract_id-keyed dedup outbox + the open_trades pop all happen in a
# single state write. Only the SEPARATE Trade Database append (a
# different file, trade_log.jsonl) can still fail and lag behind -- and
# when it does, the contract is correctly no longer tracked as open
# (equity was already, correctly, applied exactly once), so this test
# now verifies that lagging append gets retried and completed on the next
# run instead of ever being retried against equity again.

def test_trade_log_append_failure_does_not_lose_or_double_count_pnl(monkeypatch):
    state.record_open_trade(42, {
        "instrument": "frxXAUUSD", "strategy": "ema_crossover", "side": "long",
        "entry_time": "2026-01-01T00:00:00Z", "entry_price": 2000.0, "stake": 10.0,
        "risk_amount": 1.0, "equity_before": 100.0, "virtual_account_id": "champion_m30",
    })
    virtual_accounts.ensure_virtual_accounts()
    broker = _broker(open_positions_list=AsyncMock(return_value=[]))
    broker.settled_profit = AsyncMock(return_value=4.5)
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.HOLD, 2000.0, reason="n/a"))

    # commit_trade_settlement itself does not raise: the Trade Database
    # append it attempts via flush_trade_settlements is best-effort and
    # retried later, never allowed to roll back (or repeat) the equity
    # mutation that already landed in the same atomic state write. Scoped
    # to a nested context so only this one patch is undone afterward --
    # not the outer isolated_state fixture's own monkeypatches.
    with monkeypatch.context() as m:
        m.setattr(virtual_accounts, "record_trade", Mock(side_effect=RuntimeError("disk full")))
        summary = asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))
    assert summary[0]["outcome"] == "TRADE"

    # Equity applied exactly once, contract no longer tracked as open --
    # unlike the old behavior, there is nothing left to "retry" against
    # equity, because nothing was left half-done.
    assert "42" not in state.list_open_trades()
    assert state.load_state()["virtual_accounts"]["champion_m30"]["equity"] == 104.5
    assert trade_log.load_trades() == []  # the append genuinely hasn't landed yet

    # A later run (or any explicit flush) retries only the missing log
    # line -- never re-touches equity.
    virtual_accounts.flush_trade_settlements()
    trades = trade_log.load_trades()
    assert len(trades) == 1
    assert trades[0]["contract_id"] == 42
    assert trades[0]["pnl"] == 4.5
    assert state.load_state()["virtual_accounts"]["champion_m30"]["equity"] == 104.5


# 2026-09-24 review fix -- P2: the exit-side strategy is rebuilt with the
# params actually used at entry (now stored in open_trades' meta), never
# {} and never the champion's current (possibly since-reassigned)
# strategy params.

def test_exit_rebuilds_the_strategy_with_the_params_stored_at_entry(monkeypatch):
    timeframe_champion.assign("champion_h4", "donchian_breakout", {"entry_window": 55}, "reassigned since entry", {})
    state.record_open_trade(42, {
        "instrument": "frxXAUUSD", "strategy": "donchian_breakout", "strategy_params": {"entry_window": 40},
        "side": "long", "entry_time": "2026-01-01T00:00:00Z", "entry_price": 2000.0, "stake": 10.0,
        "risk_amount": 1.0, "equity_before": 100.0, "virtual_account_id": "champion_h4",
    })
    broker = _broker(open_positions_list=AsyncMock(return_value=[{"contract_id": 42, "instrument": "frxXAUUSD"}]))

    calls = []

    def spy(name, params):
        calls.append((name, params))
        strategy = Mock()
        strategy.prepare.return_value = _bars()
        strategy.signal_for_row.return_value = Signal("frxXAUUSD", Action.HOLD, 2000.0, reason="n/a")
        return strategy

    monkeypatch.setattr(champion_scheduler, "_build_strategy", spy)

    asyncio.run(champion_scheduler._run_one_champion(broker, "champion_h4"))

    # entry-side build (current assignment) sees 55; exit-side build
    # (this position's own stored meta) must see 40 -- what was actually
    # live when the trade opened, never the current reassigned params
    # and never {}.
    assert ("donchian_breakout", {"entry_window": 55}) in calls
    assert ("donchian_breakout", {"entry_window": 40}) in calls


def test_new_entries_persist_the_strategy_params_used_for_later_exit_rebuilding(monkeypatch):
    timeframe_champion.assign("champion_m30", "donchian_breakout", {"entry_window": 40}, "test", {})
    broker = _broker()
    _stub_strategy(monkeypatch, Signal("frxXAUUSD", Action.BUY, 2000.0, stop_price=1990.0, take_profit_price=2020.0, reason="broke out"))

    asyncio.run(champion_scheduler._run_one_champion(broker, "champion_m30"))

    meta = list(state.list_open_trades().values())[0]
    assert meta["strategy_params"] == {"entry_window": 40}

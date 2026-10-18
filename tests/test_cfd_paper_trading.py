import pandas as pd

import trading.cfd.paper_trading as pt
from trading.cfd import state
from trading.cfd.trade_log import load_trades
from trading.strategy.base import Action, Signal


class _FakeEntry:
    """Stands in for a trading.cfd.strategy_registry.StrategyEntry --
    decouples these tests from JSON registry persistence so a fully
    scripted, deterministic strategy can be used instead of a real
    EMA/Donchian one."""

    def __init__(self, name, version, suited_regimes, strategy):
        self.name = name
        self.version = version
        self.suited_regimes = suited_regimes
        self._strategy = strategy

    def build(self):
        return self._strategy


class _ScriptedStrategy:
    def __init__(self, actions=None):
        self.actions = actions or {}
        self._i = -1

    def prepare(self, bars):
        return bars.copy()

    def signal_for_row(self, instrument, row, prev_row, in_position):
        self._i += 1
        return self.actions.get(self._i, Signal(instrument, Action.HOLD, row["close"]))


def _bars(closes, highs=None, lows=None, start="2026-01-01"):
    idx = pd.date_range(start, periods=len(closes), freq="1h", tz="UTC")
    highs = highs or closes
    lows = lows or closes
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes}, index=idx)


def _setup(tmp_path, monkeypatch, entries):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    monkeypatch.setattr(pt, "PAPER_LOG_PATH", tmp_path / "cfd_paper_trades.jsonl")
    monkeypatch.setattr(pt, "list_by_state", lambda s: entries)


def test_no_paper_strategies_does_nothing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [])
    pt.run_paper_trading("frxXAUUSD", _bars([100, 100]), "trending")
    assert load_trades(tmp_path / "cfd_paper_trades.jsonl") == []


def test_opens_position_when_regime_matches_and_signal_fires(tmp_path, monkeypatch):
    strategy = _ScriptedStrategy({0: Signal("frxXAUUSD", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=110.0)})
    entry = _FakeEntry("scripted", "v1", ["trending"], strategy)
    _setup(tmp_path, monkeypatch, [entry])

    pt.run_paper_trading("frxXAUUSD", _bars([100, 100]), "trending")

    position = state.get_paper_position("scripted@v1", "frxXAUUSD")
    assert position is not None
    assert position["side"] == "long"
    assert position["contract_id"] < 0  # synthetic, never collides with a real Deriv id
    assert position["stake"] > 0


def test_no_entry_when_regime_does_not_match_suited_regimes(tmp_path, monkeypatch):
    strategy = _ScriptedStrategy({0: Signal("frxXAUUSD", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=110.0)})
    entry = _FakeEntry("scripted", "v1", ["trending"], strategy)
    _setup(tmp_path, monkeypatch, [entry])

    pt.run_paper_trading("frxXAUUSD", _bars([100, 100]), "ranging")

    assert state.get_paper_position("scripted@v1", "frxXAUUSD") is None


def test_hold_signal_opens_nothing(tmp_path, monkeypatch):
    strategy = _ScriptedStrategy({})  # defaults to HOLD every call
    entry = _FakeEntry("scripted", "v1", ["trending"], strategy)
    _setup(tmp_path, monkeypatch, [entry])

    pt.run_paper_trading("frxXAUUSD", _bars([100, 100]), "trending")

    assert state.get_paper_position("scripted@v1", "frxXAUUSD") is None


def test_existing_position_closes_when_price_hits_stop(tmp_path, monkeypatch):
    strategy = _ScriptedStrategy({})  # HOLD -- exit driven by price, not signal
    entry = _FakeEntry("scripted", "v1", ["trending"], strategy)
    _setup(tmp_path, monkeypatch, [entry])

    state.set_paper_position(
        "scripted@v1", "frxXAUUSD",
        {
            "contract_id": -1, "side": "long", "entry_price": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "stake": 10.0,
            "multiplier": 20, "risk_amount": 1.0, "entry_time": "2026-01-01T00:00:00+00:00",
            "regime": "trending",
        },
    )
    state.set_paper_equity("scripted@v1", 100.0)

    bars = _bars(closes=[97, 96], lows=[97, 94], highs=[97, 96])  # low=94 pierces stop=95
    pt.run_paper_trading("frxXAUUSD", bars, "trending")

    assert state.get_paper_position("scripted@v1", "frxXAUUSD") is None
    trades = load_trades(tmp_path / "cfd_paper_trades.jsonl")
    assert len(trades) == 1
    assert trades[0]["exit_price"] == 95.0
    assert trades[0]["exit_reason"] == "paper: stop_loss"
    # pnl = stake * multiplier * pct_move = 10 * 20 * (95-100)/100 = -10.0
    assert trades[0]["pnl"] == -10.0
    assert state.get_paper_equity("scripted@v1", default=0.0) == 90.0


def test_existing_position_closes_on_opposite_signal(tmp_path, monkeypatch):
    # No stop/target hit -- the strategy's own opposite signal closes it.
    strategy = _ScriptedStrategy({0: Signal("frxXAUUSD", Action.SELL, price=103.0, reason="reversal")})
    entry = _FakeEntry("scripted", "v1", ["trending"], strategy)
    _setup(tmp_path, monkeypatch, [entry])

    state.set_paper_position(
        "scripted@v1", "frxXAUUSD",
        {
            "contract_id": -1, "side": "long", "entry_price": 100.0,
            "stop_price": 50.0, "target_price": 200.0, "stake": 10.0,
            "multiplier": 20, "risk_amount": 1.0, "entry_time": "2026-01-01T00:00:00+00:00",
            "regime": "trending",
        },
    )
    state.set_paper_equity("scripted@v1", 100.0)

    bars = _bars([103, 103])
    pt.run_paper_trading("frxXAUUSD", bars, "trending")

    trades = load_trades(tmp_path / "cfd_paper_trades.jsonl")
    assert len(trades) == 1
    assert trades[0]["exit_price"] == 103.0
    assert "signal_exit" in trades[0]["exit_reason"]
    # pnl = 10 * 20 * (103-100)/100 = 6.0
    assert trades[0]["pnl"] == 6.0


def _isolated_account(strategy_tag, **overrides):
    account = {
        "account_id": "iso_test", "execution_tier": "PAPER", "strategy_tag": strategy_tag,
        "equity": 100.0, "starting_equity": 100.0, "horizon": "isolated",
        "entry_timeframe": "M15", "context_timeframes": ["H1", "M15"],
    }
    account.update(overrides)
    return account


def test_isolated_account_skips_new_entry_when_regime_not_suited(tmp_path, monkeypatch):
    """iso_meanrev_m15 in production: 4/5 real losses came from trades
    opened while the regime was "trending", even though mean_reversion@v1
    is only ever registered as suited to "ranging" -- run_virtual_account_paper
    never checked suited_regimes before opening a new position, unlike its
    sibling run_paper_trading(). This is the regression test for that gate."""
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    monkeypatch.setattr(pt, "PAPER_LOG_PATH", tmp_path / "cfd_paper_trades.jsonl")
    account = _isolated_account("meanrev_test@v1")
    monkeypatch.setattr(pt, "ensure_virtual_accounts", lambda: {"iso_test": account})
    monkeypatch.setattr(pt, "get_registry_entry", lambda name, version: _FakeEntry(name, version, ["ranging"], None))

    strategy = _ScriptedStrategy({0: Signal("frxXAUUSD", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=110.0)})
    pt.run_virtual_account_paper("iso_test", "frxXAUUSD", _bars([100, 100]), "trending", strategy)

    assert state.get_paper_position("virtual:iso_test", "frxXAUUSD") is None


def test_isolated_account_opens_new_entry_when_regime_suited(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    monkeypatch.setattr(pt, "PAPER_LOG_PATH", tmp_path / "cfd_paper_trades.jsonl")
    account = _isolated_account("meanrev_test@v1")
    monkeypatch.setattr(pt, "ensure_virtual_accounts", lambda: {"iso_test": account})
    monkeypatch.setattr(pt, "get_registry_entry", lambda name, version: _FakeEntry(name, version, ["ranging"], None))

    strategy = _ScriptedStrategy({0: Signal("frxXAUUSD", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=110.0)})
    pt.run_virtual_account_paper("iso_test", "frxXAUUSD", _bars([100, 100]), "ranging", strategy)

    position = state.get_paper_position("virtual:iso_test", "frxXAUUSD")
    assert position is not None
    assert position["side"] == "long"


def test_isolated_account_opens_regardless_when_strategy_not_in_registry(tmp_path, monkeypatch):
    """Fail open, not closed: an isolated account whose strategy_tag has no
    matching registry entry (e.g. conceptual labels like hybrid_balanced@v0
    with no real algorithm/registration) must keep behaving exactly as
    before this gate was added, not silently go dead."""
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    monkeypatch.setattr(pt, "PAPER_LOG_PATH", tmp_path / "cfd_paper_trades.jsonl")
    account = _isolated_account("unregistered_tag@v0")
    monkeypatch.setattr(pt, "ensure_virtual_accounts", lambda: {"iso_test": account})
    monkeypatch.setattr(pt, "get_registry_entry", lambda name, version: None)

    strategy = _ScriptedStrategy({0: Signal("frxXAUUSD", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=110.0)})
    pt.run_virtual_account_paper("iso_test", "frxXAUUSD", _bars([100, 100]), "trending", strategy)

    assert state.get_paper_position("virtual:iso_test", "frxXAUUSD") is not None


def test_isolated_account_manages_existing_exit_regardless_of_regime(tmp_path, monkeypatch):
    """An open position isn't abandoned just because the regime shifted --
    same principle run_paper_trading already documents for the registry-
    driven PAPER path. The new gate must only apply to new entries."""
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    monkeypatch.setattr(pt, "PAPER_LOG_PATH", tmp_path / "cfd_paper_trades.jsonl")
    account = _isolated_account("meanrev_test@v1")
    # record_virtual_close() (called on exit) reads/writes virtual accounts
    # through its own module-level state, not pt's -- seed real state
    # instead of monkeypatching pt.ensure_virtual_accounts here so that
    # write path sees "iso_test" too.
    state.set_virtual_accounts({"iso_test": account})
    monkeypatch.setattr(pt, "get_registry_entry", lambda name, version: _FakeEntry(name, version, ["ranging"], None))
    state.set_paper_position(
        "virtual:iso_test", "frxXAUUSD",
        {
            "contract_id": -1, "side": "long", "entry_price": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "stake": 10.0,
            "multiplier": 20, "risk_amount": 1.0, "entry_time": "2026-01-01T00:00:00+00:00",
            "equity_before": 100.0, "regime": "ranging",
        },
    )

    strategy = _ScriptedStrategy({})  # HOLD -- exit driven by price, not signal
    bars = _bars(closes=[97, 96], lows=[97, 94], highs=[97, 96])  # low=94 pierces stop=95
    pt.run_virtual_account_paper("iso_test", "frxXAUUSD", bars, "trending", strategy)

    assert state.get_paper_position("virtual:iso_test", "frxXAUUSD") is None
    trades = load_trades(tmp_path / "cfd_paper_trades.jsonl")
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "paper-forward: stop_loss"


def test_stake_below_min_stake_skips_the_trade(tmp_path, monkeypatch):
    from trading.config import settings

    monkeypatch.setattr(settings, "cfd_risk_per_trade", 0.0001)  # tiny -- forces stake under min_stake
    strategy = _ScriptedStrategy({0: Signal("frxXAUUSD", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=110.0)})
    entry = _FakeEntry("scripted", "v1", ["trending"], strategy)
    _setup(tmp_path, monkeypatch, [entry])

    pt.run_paper_trading("frxXAUUSD", _bars([100, 100]), "trending")

    assert state.get_paper_position("scripted@v1", "frxXAUUSD") is None

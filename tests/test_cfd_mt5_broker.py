"""Unit tests for MT5Broker, using a fake in-process stand-in for the
real `MetaTrader5` package (which is Windows-only and not installed in
this sandbox/CI) -- injected via the mt5_module constructor param."""
import types

import pytest

from trading.cfd.mt5_broker import MT5Broker, MT5NotConnectedError, MT5RequestError


def _symbol_info(**overrides):
    defaults = dict(
        visible=True,
        trade_tick_size=0.01,
        trade_tick_value=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


class FakeMT5:
    """Minimal stand-in for the MetaTrader5 module, configurable per test."""

    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    TRADE_RETCODE_DONE = 10009
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    TIMEFRAME_H1 = 16385

    def __init__(self):
        self.initialize_result = True
        self.login_result = True
        self.account_info_result = types.SimpleNamespace(
            login=12345, balance=1000.0, equity=1000.0, currency="USD"
        )
        self.symbols = {}
        self.ticks = {}
        self.order_send_result = types.SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE, order=1, volume=0.1, price=1900.0
        )
        self.positions = []
        self.selected = []
        self._last_error = (0, "no error")

    def initialize(self):
        return self.initialize_result

    def login(self, login, password, server):
        return self.login_result

    def shutdown(self):
        pass

    def last_error(self):
        return self._last_error

    def account_info(self):
        return self.account_info_result

    def symbol_info(self, symbol):
        return self.symbols.get(symbol)

    def symbol_select(self, symbol, enable):
        self.selected.append((symbol, enable))
        return True

    def symbols_get(self):
        return [types.SimpleNamespace(name=name) for name in self.symbols]

    def symbol_info_tick(self, symbol):
        return self.ticks.get(symbol)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        return None

    def order_send(self, request):
        return self.order_send_result

    def positions_get(self):
        return self.positions


def _broker(fake, **kwargs):
    kwargs.setdefault("login", "12345")
    kwargs.setdefault("password", "secret")
    kwargs.setdefault("server", "XMGlobal-Demo")
    kwargs.setdefault("mt5_module", fake)
    return MT5Broker(**kwargs)


def test_missing_credentials_raises():
    with pytest.raises(RuntimeError):
        MT5Broker(login="", password="secret", server="XMGlobal-Demo", mt5_module=FakeMT5())


def test_non_numeric_login_raises():
    with pytest.raises(RuntimeError):
        MT5Broker(login="not-a-number", password="secret", server="XMGlobal-Demo", mt5_module=FakeMT5())


def test_live_server_without_allow_flag_raises():
    with pytest.raises(RuntimeError):
        MT5Broker(login="12345", password="secret", server="XMGlobal-Real", mt5_module=FakeMT5())


def test_live_server_with_allow_flag_is_permitted():
    broker = MT5Broker(
        login="12345", password="secret", server="XMGlobal-Real", allow_live_trading=True, mt5_module=FakeMT5()
    )
    assert broker is not None


def test_demo_server_case_insensitive():
    broker = _broker(FakeMT5(), server="XMGlobal-DEMO")
    assert broker is not None


def test_connect_success_returns_account_info():
    fake = FakeMT5()
    broker = _broker(fake)
    account = broker.connect()
    assert account == {"login": 12345, "balance": 1000.0, "equity": 1000.0, "currency": "USD", "server": "XMGlobal-Demo"}


def test_connect_initialize_failure_raises_not_connected():
    fake = FakeMT5()
    fake.initialize_result = False
    broker = _broker(fake)
    with pytest.raises(MT5NotConnectedError):
        broker.connect()


def test_connect_login_failure_raises_not_connected():
    fake = FakeMT5()
    fake.login_result = False
    broker = _broker(fake)
    with pytest.raises(MT5NotConnectedError):
        broker.connect()


def test_connect_missing_account_info_raises_not_connected():
    fake = FakeMT5()
    fake.account_info_result = None
    broker = _broker(fake)
    with pytest.raises(MT5NotConnectedError):
        broker.connect()


def test_account_equity_reads_live_account_info():
    fake = FakeMT5()
    fake.account_info_result = types.SimpleNamespace(login=1, balance=500.0, equity=543.21, currency="USD")
    broker = _broker(fake)
    assert broker.account_equity() == 543.21


def test_account_equity_raises_when_unavailable():
    fake = FakeMT5()
    fake.account_info_result = None
    broker = _broker(fake)
    with pytest.raises(MT5RequestError):
        broker.account_equity()


def test_resolve_symbol_direct_hit_does_not_need_lookup():
    fake = FakeMT5()
    fake.symbols = {"XAUUSD": _symbol_info(visible=True)}
    broker = _broker(fake)
    assert broker.resolve_symbol("XAUUSD") == "XAUUSD"
    assert fake.selected == []  # already visible -- no symbol_select call needed


def test_resolve_symbol_direct_hit_selects_if_not_visible():
    fake = FakeMT5()
    fake.symbols = {"XAUUSD": _symbol_info(visible=False)}
    broker = _broker(fake)
    assert broker.resolve_symbol("XAUUSD") == "XAUUSD"
    assert fake.selected == [("XAUUSD", True)]


def test_resolve_symbol_fuzzy_match_finds_broker_suffix():
    fake = FakeMT5()
    fake.symbols = {"XAUUSD.s": _symbol_info()}
    broker = _broker(fake)
    assert broker.resolve_symbol("XAUUSD") == "XAUUSD.s"


def test_resolve_symbol_no_match_raises():
    fake = FakeMT5()
    fake.symbols = {"EURUSD": _symbol_info()}
    broker = _broker(fake)
    with pytest.raises(MT5RequestError):
        broker.resolve_symbol("XAUUSD")


def test_resolve_symbol_ambiguous_raises():
    fake = FakeMT5()
    fake.symbols = {"XAUUSD.a": _symbol_info(), "XAUUSD.b": _symbol_info()}
    broker = _broker(fake)
    with pytest.raises(MT5RequestError):
        broker.resolve_symbol("XAUUSD")


def test_get_price_reads_ask():
    fake = FakeMT5()
    fake.ticks["XAUUSD"] = types.SimpleNamespace(ask=1900.5, bid=1900.3)
    broker = _broker(fake)
    assert broker.get_price("XAUUSD") == 1900.5


def test_get_price_raises_when_no_tick():
    fake = FakeMT5()
    broker = _broker(fake)
    with pytest.raises(MT5RequestError):
        broker.get_price("XAUUSD")


def test_size_to_lots_basic():
    fake = FakeMT5()
    fake.symbols["XAUUSD"] = _symbol_info(trade_tick_size=0.01, trade_tick_value=1.0, volume_min=0.01, volume_step=0.01, volume_max=100.0)
    broker = _broker(fake)
    # risk_amount=10, stop_distance=1.0 -> loss_per_lot = (1.0/0.01)*1.0 = 100 -> raw_lots = 0.1
    lots = broker.size_to_lots("XAUUSD", risk_amount=10.0, stop_distance=1.0)
    assert lots == 0.1


def test_size_to_lots_clamped_to_volume_max():
    fake = FakeMT5()
    fake.symbols["XAUUSD"] = _symbol_info(trade_tick_size=0.01, trade_tick_value=1.0, volume_min=0.01, volume_step=0.01, volume_max=0.05)
    broker = _broker(fake)
    lots = broker.size_to_lots("XAUUSD", risk_amount=10.0, stop_distance=1.0)
    assert lots == 0.05


def test_size_to_lots_zero_when_below_volume_min():
    fake = FakeMT5()
    fake.symbols["XAUUSD"] = _symbol_info(trade_tick_size=0.01, trade_tick_value=1.0, volume_min=1.0, volume_step=0.01, volume_max=100.0)
    broker = _broker(fake)
    lots = broker.size_to_lots("XAUUSD", risk_amount=10.0, stop_distance=1.0)
    assert lots == 0.0


def test_size_to_lots_zero_when_stop_distance_zero():
    fake = FakeMT5()
    fake.symbols["XAUUSD"] = _symbol_info()
    broker = _broker(fake)
    assert broker.size_to_lots("XAUUSD", risk_amount=10.0, stop_distance=0.0) == 0.0


def test_size_to_lots_raises_when_symbol_unknown():
    fake = FakeMT5()
    broker = _broker(fake)
    with pytest.raises(MT5RequestError):
        broker.size_to_lots("XAUUSD", risk_amount=10.0, stop_distance=1.0)


def test_open_position_success_builds_correct_request():
    fake = FakeMT5()
    fake.ticks["XAUUSD"] = types.SimpleNamespace(ask=1900.5, bid=1900.3)
    broker = _broker(fake)
    result = broker.open_position("XAUUSD", "long", 0.1, 1890.0, 1920.0)
    assert result == {"ticket": 1, "volume": 0.1, "price": 1900.0}


def test_open_position_failure_raises_request_error():
    fake = FakeMT5()
    fake.ticks["XAUUSD"] = types.SimpleNamespace(ask=1900.5, bid=1900.3)
    fake.order_send_result = types.SimpleNamespace(retcode=10013, order=None, volume=None, price=None)
    broker = _broker(fake)
    with pytest.raises(MT5RequestError):
        broker.open_position("XAUUSD", "long", 0.1, 1890.0, 1920.0)


def test_open_position_raises_when_order_send_returns_none():
    fake = FakeMT5()
    fake.ticks["XAUUSD"] = types.SimpleNamespace(ask=1900.5, bid=1900.3)
    fake.order_send_result = None
    broker = _broker(fake)
    with pytest.raises(MT5RequestError):
        broker.open_position("XAUUSD", "long", 0.1, 1890.0, 1920.0)


def test_close_position_success():
    fake = FakeMT5()
    fake.ticks["XAUUSD"] = types.SimpleNamespace(ask=1900.5, bid=1900.3)
    broker = _broker(fake)
    result = broker.close_position({"ticket": 1, "symbol": "XAUUSD", "lots": 0.1, "side": "long"})
    assert result == {"ticket": 1, "price": 1900.0}


def test_open_positions_maps_by_symbol():
    fake = FakeMT5()
    fake.positions = [
        types.SimpleNamespace(symbol="XAUUSD", ticket=1, type=fake.POSITION_TYPE_BUY, volume=0.1, profit=5.0),
        types.SimpleNamespace(symbol="EURUSD", ticket=2, type=fake.POSITION_TYPE_SELL, volume=0.2, profit=-2.5),
    ]
    broker = _broker(fake)
    positions = broker.open_positions()
    assert positions == {
        "XAUUSD": {"ticket": 1, "side": "long", "lots": 0.1, "profit": 5.0},
        "EURUSD": {"ticket": 2, "side": "short", "lots": 0.2, "profit": -2.5},
    }


def test_open_positions_empty_when_none_returned():
    fake = FakeMT5()
    fake.positions = None
    broker = _broker(fake)
    assert broker.open_positions() == {}

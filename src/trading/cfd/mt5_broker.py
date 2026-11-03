"""Thin synchronous wrapper around the official `MetaTrader5` Python
package, for XM demo-account trading.

A completely separate broker/account from DerivBroker (see broker.py) --
XM only offers MetaTrader 4/5, not a WebSocket API like Deriv's, so this
talks to the MT5 *terminal* running locally via its Python bindings
instead of a remote API. That package is Windows-only and requires the
MT5 terminal to already be installed, running, and logged in on the same
machine -- there is no cloud/headless equivalent, which is why this bot
runs via Windows Task Scheduler on the user's own PC (see
scripts/run_mt5_service.py and docs/xm_mt5_setup.md), not GitHub Actions.

Key differences from Deriv's model that shape this file:
  - Position sizing is in lots, not a dollar "stake" + leverage
    "multiplier" -- size_to_lots() is the lots analog of risk.py's
    CfdRiskManager.stake_and_limits(), using the symbol's own
    trade_tick_value/trade_tick_size to convert a price-distance stop into
    a lot size that risks about risk_amount.
  - Stop-loss/take-profit are price levels on the order itself (sl/tp
    fields), not dollar P&L amounts Deriv auto-closes at -- and critically,
    those price-level sl/tp are enforced by the broker's SERVER once the
    order is placed, not by this script, so an open position stays
    protected even while the PC (and this script) is off.
  - There's no separate demo/real flag on a token the way Deriv's account
    model has -- which server you log into (e.g. "...-Demo" vs
    "...-Real") decides that, so the safety gate here checks the server
    name instead (see __init__).
  - XM's exact symbol spelling for an instrument (e.g. gold) can carry a
    broker-specific suffix (XAUUSD, XAUUSD.s, GOLD, ...) -- resolve_symbol()
    looks it up live via symbols_get()/symbol_info() rather than assuming
    one spelling, the same "confirm against a live response, don't guess"
    discipline broker.py's Deriv version uses for its own symbol names.

The `MetaTrader5` package itself is imported lazily inside _lib(), not at
module import time -- it's Windows-only and not installed in this
sandbox or on the Linux GitHub Actions runner that runs the Deriv bot, so
a top-level import would break importing this module anywhere else in
the repo. mt5_module can also be injected directly (constructor param),
which is how the unit tests exercise this file without a real MT5
terminal.
"""
import math
from typing import Optional

import pandas as pd

from trading.config import settings


class MT5RequestError(RuntimeError):
    """Raised when MetaTrader5 returns a failed/ambiguous result for an
    operation that did reach the terminal (a rejected order, an unknown
    symbol, a failed lookup) -- as opposed to MT5NotConnectedError, which
    means the terminal/account wasn't reachable at all."""


class MT5NotConnectedError(RuntimeError):
    """Raised when the MT5 terminal isn't running, not logged in, or the
    MetaTrader5 package isn't installed -- the normal condition right
    after the PC boots, before XM's MT5 terminal has been opened, or
    before requirements-mt5.txt has been installed. Callers (see
    scripts/run_mt5_service.py) should treat this as "try again next
    scheduled tick", not a crash."""


class MT5Broker:
    def __init__(
        self,
        login: Optional[str] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        allow_live_trading: Optional[bool] = None,
        mt5_module=None,
    ):
        self._login = login if login is not None else settings.mt5_login
        self._password = password if password is not None else settings.mt5_password
        self._server = server if server is not None else settings.mt5_server
        self._allow_live_trading = (
            allow_live_trading if allow_live_trading is not None else settings.mt5_allow_live_trading
        )
        if not self._login or not self._password or not self._server:
            raise RuntimeError("MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER must all be set")
        try:
            self._login = int(self._login)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"MT5_LOGIN must be numeric (got {self._login!r})") from exc

        # XM (and MT5 brokers generally) separate demo/real by which server
        # you log into (e.g. "XMGlobal-Demo" vs "XMGlobal-Real"), not by a
        # flag on a token the way Deriv's account model works (see
        # broker.py's DerivBroker.connect) -- so the safety gate checks the
        # server name instead.
        if "demo" not in self._server.lower() and not self._allow_live_trading:
            raise RuntimeError(
                f"MT5_SERVER ({self._server!r}) does not look like a demo server. "
                "Set MT5_ALLOW_LIVE_TRADING=true explicitly to trade with a real account."
            )

        self._mt5 = mt5_module  # lazily imported real MetaTrader5 module if None
        self._connected = False

    def _lib(self):
        if self._mt5 is not None:
            return self._mt5
        try:
            import MetaTrader5 as mt5  # noqa: N813 -- matches the package's own PyPI/import name
        except ImportError as exc:
            raise MT5NotConnectedError(
                "The MetaTrader5 package is not installed. This bot must run on Windows with "
                "`pip install -r requirements-mt5.txt` -- see docs/xm_mt5_setup.md."
            ) from exc
        self._mt5 = mt5
        return mt5

    def connect(self) -> dict:
        mt5 = self._lib()
        if not mt5.initialize():
            raise MT5NotConnectedError(
                f"MetaTrader5.initialize() failed ({mt5.last_error()}) -- is the XM MT5 terminal "
                "installed and running on this machine?"
            )
        authorized = mt5.login(self._login, password=self._password, server=self._server)
        if not authorized:
            raise MT5NotConnectedError(
                f"MetaTrader5.login() failed ({mt5.last_error()}) -- check MT5_LOGIN/MT5_PASSWORD/MT5_SERVER."
            )
        self._connected = True
        info = mt5.account_info()
        if info is None:
            raise MT5NotConnectedError(f"account_info() returned None right after login ({mt5.last_error()})")
        return {
            "login": info.login,
            "balance": info.balance,
            "equity": info.equity,
            "currency": info.currency,
            "server": self._server,
        }

    def close(self) -> None:
        if self._connected:
            self._lib().shutdown()
            self._connected = False

    def account_equity(self) -> float:
        info = self._lib().account_info()
        if info is None:
            raise MT5RequestError(f"account_info() returned None ({self._lib().last_error()})")
        return float(info.equity)

    def resolve_symbol(self, requested: str) -> str:
        """Returns the exact MT5 symbol name to trade for a requested
        instrument (e.g. "XAUUSD"), discovering XM's actual spelling
        (which may carry a broker-specific suffix) rather than assuming
        the requested spelling is exact. Raises MT5RequestError if there's
        no match, or more than one equally-plausible match (ambiguous)."""
        mt5 = self._lib()
        info = mt5.symbol_info(requested)
        if info is not None:
            if not info.visible:
                mt5.symbol_select(requested, True)
            return requested

        all_symbols = mt5.symbols_get() or ()
        names = [s.name for s in all_symbols]
        requested_base = requested.upper().split(".")[0]
        candidates = [n for n in names if n.upper().split(".")[0] == requested_base]
        if not candidates:
            # Fall back to a looser prefix match so a typo'd/odd suffix
            # still surfaces something actionable in the error message.
            candidates = [n for n in names if n.upper().startswith(requested_base)]
        if not candidates:
            raise MT5RequestError(
                f"No MT5 symbol matches {requested!r}. First 20 available symbols: {names[:20]!r}"
            )
        if len(candidates) > 1:
            raise MT5RequestError(
                f"Ambiguous MT5 symbol for {requested!r} -- candidates: {candidates!r}. "
                "Set MT5_INSTRUMENTS to the exact symbol name shown in the MT5 terminal's Market Watch."
            )
        chosen = candidates[0]
        info = mt5.symbol_info(chosen)
        if info is not None and not info.visible:
            mt5.symbol_select(chosen, True)
        return chosen

    def get_price(self, symbol: str) -> float:
        tick = self._lib().symbol_info_tick(symbol)
        if tick is None:
            raise MT5RequestError(f"symbol_info_tick({symbol!r}) returned None ({self._lib().last_error()})")
        return float(tick.ask)

    def get_candles(self, symbol: str, count: int = 200) -> pd.DataFrame:
        """H1 (hourly) bars -- matches EmaCrossoverStrategy's validated
        timeframe (see strategy.py's docstring)."""
        mt5 = self._lib()
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame(columns=["open", "high", "low", "close"])
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df.set_index("time")[["open", "high", "low", "close"]].sort_index()

    def size_to_lots(self, symbol: str, risk_amount: float, stop_distance: float) -> float:
        """Converts a dollar risk budget + price-distance stop into an MT5
        lot size, respecting the symbol's volume_min/volume_step/
        volume_max -- the lots analog of risk.py's CfdRiskManager.
        stake_and_limits() for Deriv's stake+multiplier model. MT5 has no
        stake/multiplier concept; P&L per lot for a given price move is
        trade_tick_value * (price_move / trade_tick_size), so that
        relationship is inverted here to solve for the lot size that
        would lose about risk_amount if price moves stop_distance against
        the position.

        Returns 0.0 if the inputs are degenerate (zero/negative stop
        distance or tick size) -- same "can't size this trade" signal
        stake_and_limits() uses, so callers (see run_mt5_service.py) can
        treat both the same way."""
        if stop_distance <= 0 or risk_amount <= 0:
            return 0.0
        info = self._lib().symbol_info(symbol)
        if info is None:
            raise MT5RequestError(f"symbol_info({symbol!r}) returned None")
        tick_size = info.trade_tick_size
        tick_value = info.trade_tick_value
        if tick_size <= 0 or tick_value <= 0:
            return 0.0

        loss_per_lot = (stop_distance / tick_size) * tick_value
        if loss_per_lot <= 0:
            return 0.0
        raw_lots = risk_amount / loss_per_lot

        step = info.volume_step or 0.01
        lots = math.floor(raw_lots / step) * step
        if lots < info.volume_min:
            return 0.0  # the risk budget can't even afford the broker's minimum lot size
        lots = min(lots, info.volume_max)
        return round(lots, 2)

    def open_position(self, symbol: str, side: str, lots: float, stop_price: float, take_profit_price: float) -> dict:
        """side is "long" or "short" (same convention as strategy.py's
        Signal/Action and DerivBroker.submit_multiplier_order)."""
        mt5 = self._lib()
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5RequestError(f"symbol_info_tick({symbol!r}) returned None ({mt5.last_error()})")
        order_type = mt5.ORDER_TYPE_BUY if side == "long" else mt5.ORDER_TYPE_SELL
        price = tick.ask if side == "long" else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lots,
            "type": order_type,
            "price": price,
            "sl": stop_price,
            "tp": take_profit_price,
            "deviation": 20,
            "magic": 990011,
            "comment": "v1-ema-crossover",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result is not None else None
            raise MT5RequestError(f"order_send failed for {symbol} ({side}): retcode={code} ({mt5.last_error()})")
        return {"ticket": result.order, "volume": result.volume, "price": result.price}

    def close_position(self, position: dict) -> dict:
        """position must have "ticket", "symbol", "lots", "side" -- the
        shape open_positions() returns, with "symbol" merged in by the
        caller (see run_mt5_service.py), matching how run_cfd_trading.py
        merges the Deriv broker's position dict with its instrument key."""
        mt5 = self._lib()
        tick = mt5.symbol_info_tick(position["symbol"])
        if tick is None:
            raise MT5RequestError(f"symbol_info_tick({position['symbol']!r}) returned None ({mt5.last_error()})")
        side = position["side"]
        order_type = mt5.ORDER_TYPE_SELL if side == "long" else mt5.ORDER_TYPE_BUY
        price = tick.bid if side == "long" else tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position["symbol"],
            "volume": position["lots"],
            "type": order_type,
            "position": position["ticket"],
            "price": price,
            "deviation": 20,
            "magic": 990011,
            "comment": "v1-ema-crossover-close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result is not None else None
            raise MT5RequestError(
                f"order_send (close) failed for ticket {position['ticket']}: retcode={code} ({mt5.last_error()})"
            )
        return {"ticket": result.order, "price": result.price}

    def open_positions(self) -> dict:
        """Returns {symbol: {"ticket": int, "side": "long"|"short",
        "lots": float, "profit": float}} for every open position -- the
        MT5 analog of DerivBroker.open_positions(), with the same "assumes
        at most one open position per symbol" caveat (true for this
        strategy, which never opens a second position in a symbol it's
        already in). "profit" is MT5's live floating P&L for the
        position, used by run_mt5_service.py as the realized P&L at the
        moment it decides to close (MT5's order_send result for a closing
        deal doesn't itself report P&L the way Deriv's sell response
        does)."""
        mt5 = self._lib()
        positions = mt5.positions_get()
        if positions is None:
            positions = ()
        result = {}
        for p in positions:
            side = "long" if p.type == mt5.POSITION_TYPE_BUY else "short"
            result[p.symbol] = {"ticket": p.ticket, "side": side, "lots": p.volume, "profit": p.profit}
        return result

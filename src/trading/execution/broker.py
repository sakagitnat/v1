import time

from trading.config import settings


class AlpacaBroker:
    """Thin wrapper around Alpaca's trading API.

    Refuses to touch a live (real-money) account unless ALPACA_PAPER=false
    AND ALLOW_LIVE_TRADING=true are both set explicitly in the environment —
    see Settings.is_live_trading_allowed().

    Uses notional (dollar-amount) buys so small accounts can trade
    fractional shares of expensive stocks. Alpaca doesn't support bracket
    orders (built-in stop-loss + take-profit) for fractional quantities, so
    entries are followed by two independent GTC orders -- a stop and a
    limit -- for the exact filled quantity, instead of one bracket order.
    """

    def __init__(self):
        from alpaca.trading.client import TradingClient

        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY are not set")

        live_requested = not settings.alpaca_paper
        if live_requested and not settings.allow_live_trading:
            raise RuntimeError(
                "Refusing to start: ALPACA_PAPER=false but ALLOW_LIVE_TRADING is not true. "
                "Set ALLOW_LIVE_TRADING=true explicitly to trade with real money."
            )

        self.client = TradingClient(
            settings.alpaca_api_key, settings.alpaca_secret_key, paper=settings.alpaca_paper
        )

    def account_equity(self) -> float:
        return float(self.client.get_account().equity)

    def open_symbols(self) -> set[str]:
        return {p.symbol for p in self.client.get_all_positions()}

    def get_position_qty(self, symbol: str) -> float:
        try:
            return float(self.client.get_open_position(symbol).qty)
        except Exception:
            return 0.0

    def wait_for_position_qty(self, symbol: str, attempts: int = 5, delay_seconds: float = 1.0) -> float:
        """Poll until a just-submitted buy has filled and shows up as a
        position, so the follow-up stop/limit orders use the exact filled
        quantity rather than an estimate."""
        for _ in range(attempts):
            qty = self.get_position_qty(symbol)
            if qty > 0:
                return qty
            time.sleep(delay_seconds)
        return 0.0

    def submit_notional_buy(self, symbol: str, notional: float):
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        order = MarketOrderRequest(
            symbol=symbol,
            notional=round(notional, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        return self.client.submit_order(order)

    def submit_stop_sell(self, symbol: str, qty: float, stop_price: float):
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import StopOrderRequest

        order = StopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            stop_price=round(stop_price, 2),
        )
        return self.client.submit_order(order)

    def submit_limit_sell(self, symbol: str, qty: float, limit_price: float):
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest

        order = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2),
        )
        return self.client.submit_order(order)

    def get_last_filled_sell_price(self, symbol: str) -> float:
        """The fill price of the most recent filled SELL order for symbol --
        used to credit a bucket's cash with the actual sale proceeds when a
        stop or limit order closes its position (see buckets.py)."""
        from alpaca.trading.enums import OrderSide, QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        request = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED, symbols=[symbol], side=OrderSide.SELL, limit=5
        )
        orders = self.client.get_orders(request)
        filled = [o for o in orders if getattr(o, "filled_avg_price", None)]
        if not filled:
            return 0.0
        filled.sort(key=lambda o: o.filled_at, reverse=True)
        return float(filled[0].filled_avg_price)

    def cancel_open_orders(self, symbol: str):
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        request = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        for order in self.client.get_orders(request):
            self.client.cancel_order_by_id(order.id)

    def close_position(self, symbol: str):
        self.cancel_open_orders(symbol)
        return self.client.close_position(symbol)

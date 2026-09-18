from trading.config import settings


class AlpacaBroker:
    """Thin wrapper around Alpaca's trading API.

    Refuses to touch a live (real-money) account unless ALPACA_PAPER=false
    AND ALLOW_LIVE_TRADING=true are both set explicitly in the environment —
    see Settings.is_live_trading_allowed().
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

    def submit_bracket_buy(self, symbol: str, qty: int, stop_price: float, take_profit_price: float):
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest

        order = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=round(stop_price, 2)),
            take_profit=TakeProfitRequest(limit_price=round(take_profit_price, 2)),
        )
        return self.client.submit_order(order)

    def close_position(self, symbol: str):
        return self.client.close_position(symbol)

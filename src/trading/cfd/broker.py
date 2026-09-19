import itertools
import json

import pandas as pd

from trading.config import settings

WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"


class DerivBroker:
    """Thin async wrapper around Deriv's WebSocket API for Multipliers
    (leveraged forex/gold/commodity) trading.

    A completely separate account and safety model from the Alpaca stock
    system (see AlpacaBroker) -- but Deriv's account model differs from
    Alpaca/OANDA's "same URL, paper vs live flag" pattern: an API token is
    already scoped to one specific account (demo/virtual or real) at the
    moment it's created, there's no separate practice/live base URL to
    switch. So the safety check here happens *after* connecting: the
    authorize response's is_virtual field says which kind of account this
    token is for, and we refuse to proceed on a real (non-virtual) account
    unless CFD_ALLOW_LIVE_TRADING is explicitly set -- same protective
    intent as the Alpaca/OANDA dual gate, enforced a different way because
    Deriv's account model itself is different.

    UNTESTED against the real API as of writing -- built from Deriv's API
    documentation but not yet exercised against a real demo account (no
    token was available yet). Validate every method here, especially
    submit_multiplier_order's stop_loss/take_profit unit conversion
    (dollar amounts, not price levels -- see scheduler.py), before
    trusting it with even demo money.
    """

    def __init__(self):
        if not settings.deriv_api_token:
            raise RuntimeError("DERIV_API_TOKEN is not set")
        self._app_id = settings.deriv_app_id
        self._token = settings.deriv_api_token
        self._ws = None
        self._req_id = itertools.count(1)

    async def connect(self) -> dict:
        import websockets

        self._ws = await websockets.connect(WS_URL.format(app_id=self._app_id))
        auth = await self._request({"authorize": self._token})
        is_virtual = bool(auth["authorize"].get("is_virtual"))
        if not is_virtual and not settings.cfd_allow_live_trading:
            await self.close()
            raise RuntimeError(
                "Refusing to start: this API token authorizes a REAL (non-virtual) Deriv "
                "account, but CFD_ALLOW_LIVE_TRADING is not true. Set CFD_ALLOW_LIVE_TRADING=true "
                "explicitly to trade with real money."
            )
        return auth

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _request(self, payload: dict) -> dict:
        req_id = next(self._req_id)
        await self._ws.send(json.dumps({**payload, "req_id": req_id}))
        while True:
            resp = json.loads(await self._ws.recv())
            if resp.get("req_id") != req_id:
                continue  # a message for a different in-flight request; keep waiting
            if "error" in resp:
                raise RuntimeError(f"Deriv API error ({list(payload)[0]}): {resp['error'].get('message')}")
            return resp

    async def account_equity(self) -> float:
        resp = await self._request({"balance": 1})
        return float(resp["balance"]["balance"])

    async def open_positions(self) -> dict:
        """Returns {symbol: {"contract_id": int, "side": "long"|"short"}}
        for every open multiplier contract."""
        resp = await self._request({"portfolio": 1})
        positions = {}
        for c in resp["portfolio"]["contracts"]:
            positions[c["symbol"]] = {
                "contract_id": c["contract_id"],
                "side": "long" if c["contract_type"] == "MULTUP" else "short",
            }
        return positions

    async def get_candles(self, symbol: str, granularity_seconds: int = 900, count: int = 200) -> pd.DataFrame:
        """granularity_seconds must be one of Deriv's supported candle
        sizes (60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 86400)
        -- 900 = 15 minutes."""
        resp = await self._request(
            {"ticks_history": symbol, "style": "candles", "granularity": granularity_seconds, "count": count, "end": "latest"}
        )
        rows = [
            {
                "time": pd.Timestamp(c["epoch"], unit="s", tz="UTC"),
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
            }
            for c in resp.get("candles", [])
        ]
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close"])
        return pd.DataFrame(rows).set_index("time").sort_index()

    async def submit_multiplier_order(
        self, symbol: str, side: str, stake: float, multiplier: int, stop_loss_amount: float, take_profit_amount: float
    ) -> dict:
        """side is "long" (MULTUP) or "short" (MULTDOWN). stake is the
        amount risked -- Deriv's multipliers cap loss at this stake by
        design, unlike traditional leveraged CFDs where a big enough
        adverse move can lose more than the position's margin.
        stop_loss_amount/take_profit_amount are dollar P&L amounts (Deriv
        auto-closes once the contract's profit/loss reaches that amount),
        NOT price levels -- see scheduler.py for the conversion from the
        strategy's ATR-based price distance."""
        contract_type = "MULTUP" if side == "long" else "MULTDOWN"
        proposal = await self._request(
            {
                "proposal": 1,
                "contract_type": contract_type,
                "symbol": symbol,
                "amount": round(stake, 2),
                "basis": "stake",
                "currency": "USD",
                "multiplier": multiplier,
                "limit_order": {
                    "stop_loss": round(stop_loss_amount, 2),
                    "take_profit": round(take_profit_amount, 2),
                },
            }
        )
        proposal_id = proposal["proposal"]["id"]
        price = proposal["proposal"]["ask_price"]
        return await self._request({"buy": proposal_id, "price": price})

    async def close_position(self, contract_id: int) -> dict:
        return await self._request({"sell": contract_id, "price": 0})

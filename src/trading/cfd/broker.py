import itertools
import json

import pandas as pd

from trading.config import settings

OPTIONS_API_BASE = "https://api.derivws.com/trading/v1/options"


class DerivBroker:
    """Thin async wrapper around Deriv's WebSocket API for Multipliers
    (leveraged forex/gold/commodity) trading.

    A completely separate account and safety model from the Alpaca stock
    system (see AlpacaBroker) -- but Deriv's account model differs from
    Alpaca/OANDA's "same URL, paper vs live flag" pattern: an API token is
    already scoped to one specific account (demo/virtual or real) at the
    moment it's created, there's no separate practice/live base URL to
    switch.

    Connection flow for PAT-style tokens (the "pat_..." prefix Deriv's
    current account/api-token page issues), confirmed directly with Deriv
    support after the classic "wss://ws.derivws.com/websockets/v3" +
    {"authorize": token} approach documented in most examples online
    turned out to be for the older/OAuth token style only:
      1. GET  {OPTIONS_API_BASE}/accounts with Authorization: Bearer +
         Deriv-App-ID headers -- lists the account(s) this token can act
         on, and whether each is real or virtual (demo).
      2. POST {OPTIONS_API_BASE}/accounts/{account_id}/otp, same headers
         -- issues a short-lived (120s), single-use one-time-password and
         a ready-to-use WebSocket URL with it attached.
      3. Connect to that URL directly. The connection is already
         authenticated -- no separate "authorize" message is sent or
         needed once connected this way.
    Multipliers contracts are confirmed (by Deriv support) to be covered
    by this same flow, despite the "options" in the URL path -- that's
    Deriv's product-family name for this whole newer API surface, not a
    restriction to binary/digital options contracts specifically. A
    genuinely different product -- MT5 leveraged forex/CFDs -- should NOT
    use this endpoint; that's the "CFDs" account the README warns is a
    dead end for API access (see "CFD/forex trading (Deriv)").

    Safety gate: since there's no separate practice/live base URL to
    force, the check happens right after step 1 -- picks the account
    whose account_type is "demo" among the ones this token authorizes
    unless CFD_ALLOW_LIVE_TRADING is explicitly set (which picks "real"
    instead), same protective intent as the Alpaca/OANDA dual gate. This
    matters because Deriv gives every signup an unverified real-money
    account automatically alongside any demo account, even for users who
    only ever use demo -- so a token can authorize both, and accounts[0]
    is not necessarily the demo one.

    Confirmed end-to-end against a live demo account (see scripts/
    cfd_cli.py's test-order/close-position commands): connect, submit_
    multiplier_order (buy), open_positions, and close_position (sell) all
    round-tripped successfully. Field names that differ from the more
    commonly documented (legacy) Deriv API surface, discovered this way:
      - /accounts response: {"account_id": str, "balance": str,
        "currency": str, "group": str, "status": str, "account_type":
        "demo"|"real"} -- no "is_virtual" field.
      - proposal request: "underlying_symbol", not "symbol".
      - portfolio response contracts: "underlying_symbol", not "symbol".
    A brand-new contract can't be sold until Deriv processes its first
    price tick -- close_position right after submit_multiplier_order can
    transiently return "Waiting for entry tick"; retry after a couple of
    seconds (see cfd_cli.py's test-order for an example).

    Not yet validated: the actual forex/gold instruments in cfd_instruments
    (frxXAUUSD etc.) only got as far as proposal request validation before
    market-closed errors (tested on a weekend) -- the multiplier values
    Deriv accepts per-instrument vary a lot (a synthetic index accepted
    only 40/100/200/300/400, not the default 20) and haven't been checked
    for the real trading instruments yet. Also unverified: the strategy's
    stop_loss/take_profit dollar-amount conversion in scheduler.py, and
    the EmaCrossoverStrategy's parameters aren't backtested.
    """

    def __init__(self):
        if not settings.deriv_api_token:
            raise RuntimeError("DERIV_API_TOKEN is not set")
        self._app_id = settings.deriv_app_id
        self._token = settings.deriv_api_token
        self._ws = None
        self._req_id = itertools.count(1)

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}", "Deriv-App-ID": self._app_id}

    async def connect(self) -> dict:
        import requests
        import websockets

        accounts_resp = requests.get(f"{OPTIONS_API_BASE}/accounts", headers=self._auth_headers())
        if not accounts_resp.ok:
            raise RuntimeError(
                f"Deriv API error (GET /accounts): HTTP {accounts_resp.status_code} -- {accounts_resp.text}"
            )
        accounts = accounts_resp.json().get("data") or []
        if not accounts:
            raise RuntimeError("Deriv API: no accounts found for this token (GET /accounts returned none)")

        # A Deriv token can authorize several accounts at once (Deriv creates
        # an unverified real-money account for every signup automatically,
        # alongside any demo account -- even for users who never touch it).
        # Pick the account matching the safety mode explicitly instead of
        # blindly taking accounts[0], which could silently select the real
        # account when a demo one was intended.
        wanted_type = "demo" if not settings.cfd_allow_live_trading else "real"
        account = next((a for a in accounts if a.get("account_type") == wanted_type), None)
        if account is None:
            raise RuntimeError(
                f"Deriv API: this token has no {wanted_type.upper()} account "
                f"among {len(accounts)} account(s) it authorizes: {accounts!r}. "
                + (
                    "Set CFD_ALLOW_LIVE_TRADING=true explicitly to trade with real money."
                    if wanted_type == "demo"
                    else "Create/use a token scoped to a real account, or unset CFD_ALLOW_LIVE_TRADING."
                )
            )
        account_id = account["account_id"]

        otp_resp = requests.post(f"{OPTIONS_API_BASE}/accounts/{account_id}/otp", headers=self._auth_headers())
        if not otp_resp.ok:
            raise RuntimeError(
                f"Deriv API error (POST /accounts/{account_id}/otp): HTTP {otp_resp.status_code} -- {otp_resp.text}"
            )
        ws_url = otp_resp.json()["data"]["url"]

        self._ws = await websockets.connect(ws_url)
        return account

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
            symbol = c.get("underlying_symbol", c.get("symbol"))
            if symbol is None:
                raise RuntimeError(f"Deriv API: portfolio contract has neither underlying_symbol nor symbol: {c!r}")
            positions[symbol] = {
                "contract_id": c["contract_id"],
                "side": "long" if c["contract_type"] == "MULTUP" else "short",
            }
        return positions

    async def get_candles(
        self, symbol: str, granularity_seconds: int = 900, count: int = 200, end: str | int = "latest"
    ) -> pd.DataFrame:
        """granularity_seconds must be one of Deriv's supported candle
        sizes (60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 86400)
        -- 900 = 15 minutes. end defaults to "latest"; pass a Unix epoch to
        page further back in history (e.g. the oldest candle's epoch minus
        granularity_seconds from a previous call) -- a single request
        returns at most a few thousand candles, not a full backtest's
        worth of history."""
        resp = await self._request(
            {"ticks_history": symbol, "style": "candles", "granularity": granularity_seconds, "count": count, "end": end}
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
                "underlying_symbol": symbol,
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

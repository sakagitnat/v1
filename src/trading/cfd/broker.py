import asyncio
import itertools
import json
import math

import pandas as pd

from trading.config import settings

OPTIONS_API_BASE = "https://api.derivws.com/trading/v1/options"


class DerivRequestError(RuntimeError):
    """Same RuntimeError callers already catch, plus which request stage
    failed (`stage`, the payload's own top-level key: "proposal", "buy",
    "sell", ...) -- lets a caller that submits an order in two stages
    (request a price, then buy it) tell "the price request itself failed,
    nothing was risked" (stage == "proposal") apart from "the buy request
    failed or its result is unknown" (stage == "buy", genuinely ambiguous:
    Deriv may have processed it before the error/timeout). See quota.py's
    run_quotas() for why that distinction matters -- treating both the
    same way either leaves a stuck pending-entry marker after a definitely-
    safe proposal rejection, or (worse) silently discards genuinely
    unresolved order state."""

    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(f"Deriv API error ({stage}): {message}")


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

    Full order lifecycle (connect, buy, portfolio read, sell) is now also
    confirmed against a REAL market instrument, not just a synthetic
    index: cryBTCUSD (crypto, via list_active_symbols()) round-tripped
    successfully on a Saturday, since crypto trades 24/7 on Deriv unlike
    forex/gold which close on weekends -- useful for testing when the
    default cfd_instruments' own markets are shut. Confirmed multiplier
    values differ by instrument here too: cryBTCUSD accepts
    100/200/300/500/800, not the default 20 (same "check the error, don't
    guess" pattern as the earlier synthetic-index multiplier discovery).

    Still not validated: the actual forex/gold instruments in
    cfd_instruments (frxXAUUSD etc.) themselves -- only got as far as
    proposal request validation before market-closed errors (tested on a
    weekend). The order-placement *mechanism* is now proven correct
    end-to-end on a real instrument, so this remaining gap is about
    frxXAUUSD/frxEURUSD/etc.'s own market hours and multiplier values
    specifically, not an unproven code path in general. Also unverified:
    the EmaCrossoverStrategy's parameters were validated on forex/gold
    data only (see strategy.py's docstring) -- NOT re-validated for
    crypto's different volatility profile, so cryBTCUSD/cryETHUSD
    shouldn't be added to live cfd_instruments without their own
    backtest first, despite the order mechanism itself working fine.
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

    async def _bootstrap_request(self, method: str, path: str):
        """Retry connection bootstrap only, NEVER buy/sell requests.

        An OTP request may mint an unused credential after an ambiguous
        response, but cannot place a trade. Each retry requests a fresh OTP.
        Transport failures are bounded; auth, rate-limit and other HTTP
        errors fail immediately. Do not expose response bodies or OTP URLs.
        """
        import requests

        for attempt in range(3):
            try:
                response = await asyncio.to_thread(
                    requests.request, method, f"{OPTIONS_API_BASE}{path}",
                    headers=self._auth_headers(), timeout=(5, 15),
                    allow_redirects=False,
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt == 2:
                    raise RuntimeError("Deriv bootstrap transport failed after 3 attempts") from None
                await asyncio.sleep(2 ** attempt)
                continue
            if not 200 <= response.status_code < 300:
                status = response.status_code
                response.close()
                raise RuntimeError(f"Deriv bootstrap HTTP {status}")
            return response

    async def connect(self) -> dict:
        import websockets

        accounts_resp = await self._bootstrap_request("GET", "/accounts")
        try:
            accounts = accounts_resp.json().get("data") or []
        finally:
            accounts_resp.close()
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

        otp_resp = await self._bootstrap_request("POST", f"/accounts/{account_id}/otp")
        try:
            ws_url = otp_resp.json()["data"]["url"]
        finally:
            otp_resp.close()

        self._ws = await websockets.connect(ws_url, open_timeout=15, close_timeout=5)
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
                raise DerivRequestError(list(payload)[0], resp["error"].get("message"))
            return resp

    async def account_equity(self) -> float:
        resp = await self._request({"balance": 1})
        return float(resp["balance"]["balance"])

    async def open_positions(self) -> dict:
        """Returns {symbol: {"contract_id": int, "side": "long"|"short"}}
        for every open multiplier contract -- COLLAPSES to at most one
        entry per symbol, silently keeping only one contract's data if
        more than one is open on the same symbol. No longer safe for
        trading.cfd.scheduler's main loop to rely on for position
        tracking: partial-close (see trading.cfd.exit_manager) means a
        symbol can legitimately hold two simultaneous contracts (a
        "scalp" leg and a "runner" leg) -- use open_positions_list() (a
        flat, never-collapsed list) or open_contract_ids() (bare ids
        only) for anything that needs to see every contract, not just
        one per symbol. Kept only for callers that genuinely never hold
        more than one contract per symbol (e.g.
        scripts/burn_demo_balance.py)."""
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

    async def open_positions_list(self) -> list[dict]:
        """Like open_positions(), but returns every open contract as a
        flat list, never collapsed by symbol -- for a caller that may
        legitimately hold more than one simultaneous contract on the
        same instrument, e.g. scheduler.py's partial-close "scalp"/
        "runner" leg split (see trading.cfd.exit_manager). Each dict is
        {"contract_id": int, "instrument": str, "side": "long"|"short"} --
        same field parsing as open_positions(), just not keyed/collapsed
        by symbol."""
        resp = await self._request({"portfolio": 1})
        positions = []
        for c in resp["portfolio"]["contracts"]:
            symbol = c.get("underlying_symbol", c.get("symbol"))
            if symbol is None:
                raise RuntimeError(f"Deriv API: portfolio contract has neither underlying_symbol nor symbol: {c!r}")
            positions.append({
                "contract_id": c["contract_id"],
                "instrument": symbol,
                "side": "long" if c["contract_type"] == "MULTUP" else "short",
            })
        return positions

    async def open_contract_ids(self) -> set[int]:
        """Returns the raw set of open contract_ids, without collapsing
        by symbol -- unlike open_positions(), this correctly reflects
        several simultaneous open contracts on the same symbol."""
        resp = await self._request({"portfolio": 1})
        return {c["contract_id"] for c in resp["portfolio"]["contracts"]}

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

    async def get_ticks(self, symbol: str, count: int = 500, end: str | int = "latest") -> pd.DataFrame:
        """Return raw tick history for sub-minute/seconds research.

        Deriv candles bottom out at 60 seconds, so seconds-level research
        must use tick data rather than inventing unsupported 5s/10s candles.
        The returned frame has UTC time index and one price column.
        """
        resp = await self._request(
            {"ticks_history": symbol, "style": "ticks", "count": count, "end": end}
        )
        history = resp.get("history") or {}
        times = history.get("times") or []
        prices = history.get("prices") or []
        rows = [
            {"time": pd.Timestamp(int(t), unit="s", tz="UTC"), "price": float(p)}
            for t, p in zip(times, prices)
        ]
        if not rows:
            return pd.DataFrame(columns=["price"])
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

    async def settled_profit(self, contract_id: int) -> float:
        """Read contract-level realized profit; never infer it from balance.

        Fail closed if settlement is not yet visible or the response cannot
        be attributed to this USD contract. The caller retains metadata.
        """
        response = await asyncio.wait_for(
            self._request({"proposal_open_contract": 1, "contract_id": contract_id}),
            timeout=20,
        )
        data = response.get("proposal_open_contract") or {}
        if (str(data.get("contract_id")) != str(contract_id)
                or data.get("is_sold") not in (1, True, "1")
                or data.get("currency") != "USD"):
            raise RuntimeError("Contract settlement not confirmed")
        try:
            if isinstance(data.get("profit"), bool):
                raise ValueError
            profit = float(data["profit"])
        except (KeyError, ValueError, TypeError):
            raise RuntimeError("Contract settlement profit is missing or invalid") from None
        if not math.isfinite(profit):
            raise RuntimeError("Contract settlement profit is not finite")
        return round(profit, 2)

    async def list_active_symbols(self) -> list[dict]:
        """Returns Deriv's own list of tradable symbols -- used to
        discover real instrument names (e.g. for crypto) rather than
        guessing them, the same "confirm against a live response, don't
        assume" discipline as everything else in this file.

        No "product_type" param (unlike Deriv's classic/legacy API docs,
        which show one) -- confirmed by a live error against this
        project's newer /trading/v1/options flow: "Input validation
        failed: Properties not allowed: product_type."

        Each dict's identifier/name fields are "underlying_symbol" and
        "underlying_symbol_name" -- NOT "symbol"/"display_name" as
        classic-API docs would suggest (same underlying_symbol-not-symbol
        pattern already seen in the proposal request and portfolio
        response elsewhere in this file). Confirmed live: crypto is
        cryBTCUSD ("BTC/USD") and cryETHUSD ("ETH/USD"), market=
        "cryptocurrency" -- and unlike frxXAUUSD/frxEURUSD etc., these
        trade 24/7 (exchange_is_open=1 confirmed on a Saturday), useful
        for testing when forex/gold markets are closed on weekends.
        Other useful fields: market, submarket, exchange_is_open,
        is_trading_suspended, pip_size, trade_count."""
        resp = await self._request({"active_symbols": "brief"})
        return resp.get("active_symbols", [])

import pandas as pd

from trading.config import settings

PRACTICE_URL = "https://api-fxpractice.oanda.com"
LIVE_URL = "https://api-fxtrade.oanda.com"


class OandaBroker:
    """Thin wrapper around OANDA's v20 REST API for CFD/forex trading.

    A completely separate account and safety gate from the Alpaca stock
    system (see AlpacaBroker) -- refuses to touch a live (real-money)
    account unless OANDA_PRACTICE=false AND CFD_ALLOW_LIVE_TRADING=true are
    both set explicitly, mirroring the same dual-gate pattern.

    UNTESTED against the real API as of writing -- built from OANDA's v20
    documentation but not yet exercised against a real practice account
    (no token was available yet). Validate every method here against a
    real OANDA practice account before trusting it with even paper money.
    """

    def __init__(self):
        if not settings.oanda_api_token or not settings.oanda_account_id:
            raise RuntimeError("OANDA_API_TOKEN / OANDA_ACCOUNT_ID are not set")

        live_requested = not settings.oanda_practice
        if live_requested and not settings.cfd_allow_live_trading:
            raise RuntimeError(
                "Refusing to start: OANDA_PRACTICE=false but CFD_ALLOW_LIVE_TRADING is not "
                "true. Set CFD_ALLOW_LIVE_TRADING=true explicitly to trade with real money."
            )

        import requests

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {settings.oanda_api_token}",
                "Content-Type": "application/json",
            }
        )
        self._base_url = PRACTICE_URL if settings.oanda_practice else LIVE_URL
        self._account_id = settings.oanda_account_id

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def account_equity(self) -> float:
        resp = self._session.get(self._url(f"/v3/accounts/{self._account_id}/summary"))
        resp.raise_for_status()
        return float(resp.json()["account"]["NAV"])

    def open_positions(self) -> dict:
        """Returns {instrument: {"units": float, "side": "long"|"short"}} for
        every instrument with an open position (non-zero units)."""
        resp = self._session.get(self._url(f"/v3/accounts/{self._account_id}/openPositions"))
        resp.raise_for_status()
        positions = {}
        for p in resp.json().get("positions", []):
            long_units = float(p["long"]["units"])
            short_units = float(p["short"]["units"])
            if long_units != 0:
                positions[p["instrument"]] = {"units": long_units, "side": "long"}
            elif short_units != 0:
                positions[p["instrument"]] = {"units": short_units, "side": "short"}
        return positions

    def get_candles(self, instrument: str, granularity: str = "M15", count: int = 200) -> pd.DataFrame:
        """Recent OHLC candles as a DataFrame indexed by UTC time, columns
        open/high/low/close/volume. Only completed candles are included --
        the current, still-forming candle is dropped."""
        resp = self._session.get(
            self._url(f"/v3/instruments/{instrument}/candles"),
            params={"granularity": granularity, "count": count, "price": "M"},
        )
        resp.raise_for_status()
        rows = []
        for c in resp.json().get("candles", []):
            if not c.get("complete"):
                continue
            mid = c["mid"]
            rows.append(
                {
                    "time": pd.Timestamp(c["time"]),
                    "open": float(mid["o"]),
                    "high": float(mid["h"]),
                    "low": float(mid["l"]),
                    "close": float(mid["c"]),
                    "volume": int(c["volume"]),
                }
            )
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return pd.DataFrame(rows).set_index("time").sort_index()

    def submit_market_order(
        self, instrument: str, units: int, stop_loss_price: float, take_profit_price: float
    ) -> dict:
        """units positive = buy/long, negative = sell/short. Stop-loss and
        take-profit are attached to the order itself (stopLossOnFill /
        takeProfitOnFill) so protection is live the instant it fills --
        unlike the stock system, no separate re-arming step is needed."""
        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"timeInForce": "GTC", "price": f"{stop_loss_price:.5f}"},
                "takeProfitOnFill": {"price": f"{take_profit_price:.5f}"},
            }
        }
        resp = self._session.post(self._url(f"/v3/accounts/{self._account_id}/orders"), json=body)
        resp.raise_for_status()
        return resp.json()

    def close_position(self, instrument: str, side: str) -> dict:
        """side is "long" or "short" (whichever open_positions() reported)."""
        key = "longUnits" if side == "long" else "shortUnits"
        resp = self._session.put(
            self._url(f"/v3/accounts/{self._account_id}/positions/{instrument}/close"),
            json={key: "ALL"},
        )
        resp.raise_for_status()
        return resp.json()

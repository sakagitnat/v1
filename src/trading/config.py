import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _default_watchlist() -> list[str]:
    # GLD = SPDR Gold Shares ETF -- trades like any other equity on Alpaca
    # (no separate commodities/futures access needed), so it slots in here.
    raw = os.getenv("WATCHLIST", "SPY,AAPL,MSFT,GOOGL,AMZN,NVDA,GLD")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _default_cfd_instruments() -> list[str]:
    # Deriv's Multipliers symbol names use an "frx" prefix (frxXAUUSD, not
    # XAU/USD or XAU_USD). Gold plus the most liquid major pairs to start.
    raw = os.getenv("CFD_INSTRUMENTS", "frxXAUUSD,frxEURUSD,frxGBPUSD,frxUSDJPY")
    return [s.strip() for s in raw.split(",") if s.strip()]


@dataclass
class Settings:
    alpaca_api_key: str = field(default_factory=lambda: os.getenv("ALPACA_API_KEY", ""))
    alpaca_secret_key: str = field(default_factory=lambda: os.getenv("ALPACA_SECRET_KEY", ""))
    alpaca_paper: bool = field(default_factory=lambda: _env_bool("ALPACA_PAPER", True))
    allow_live_trading: bool = field(default_factory=lambda: _env_bool("ALLOW_LIVE_TRADING", False))
    watchlist: list[str] = field(default_factory=_default_watchlist)
    regime_symbol: str = field(default_factory=lambda: os.getenv("REGIME_SYMBOL", "SPY").strip().upper())
    risk_per_trade: float = field(default_factory=lambda: float(os.getenv("RISK_PER_TRADE", "0.01")))
    max_open_positions: int = field(default_factory=lambda: int(os.getenv("MAX_OPEN_POSITIONS", "5")))
    max_daily_loss_pct: float = field(
        default_factory=lambda: float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))
    )
    ratchet_trigger_pct: float = field(
        default_factory=lambda: float(os.getenv("RATCHET_TRIGGER_PCT", "0.20"))
    )
    ratchet_bank_fraction: float = field(
        default_factory=lambda: float(os.getenv("RATCHET_BANK_FRACTION", "0.5"))
    )
    withdrawal_multiple: float = field(
        default_factory=lambda: float(os.getenv("WITHDRAWAL_MULTIPLE", "2.0"))
    )
    bucket_activation_multiple: float = field(
        default_factory=lambda: float(os.getenv("BUCKET_ACTIVATION_MULTIPLE", "3.0"))
    )
    bucket_safe_fraction: float = field(
        default_factory=lambda: float(os.getenv("BUCKET_SAFE_FRACTION", "0.5"))
    )

    # CFD/forex (Deriv) -- a separate account, separate safety gate, separate
    # everything from the Alpaca stock system above. See src/trading/cfd/.
    #
    # Tried OANDA first, but the OANDA division reachable from Thailand
    # ("OANDA Global Markets") doesn't support the v20 REST API at all --
    # only MetaTrader, which puts us back in the same paid-bridge problem
    # as XM. Deriv has its own free WebSocket API directly, reachable from
    # a Thailand signup, and needs no separate account ID: the token itself
    # is already scoped to one specific account (demo or real) when it's
    # created, unlike Alpaca/OANDA's separate paper/live URL switch.
    deriv_api_token: str = field(default_factory=lambda: os.getenv("DERIV_API_TOKEN", ""))
    deriv_app_id: str = field(default_factory=lambda: os.getenv("DERIV_APP_ID", "1089"))
    cfd_allow_live_trading: bool = field(
        default_factory=lambda: _env_bool("CFD_ALLOW_LIVE_TRADING", False)
    )
    cfd_instruments: list[str] = field(default_factory=_default_cfd_instruments)
    cfd_risk_per_trade: float = field(
        default_factory=lambda: float(os.getenv("CFD_RISK_PER_TRADE", "0.01"))
    )
    cfd_max_open_positions: int = field(
        default_factory=lambda: int(os.getenv("CFD_MAX_OPEN_POSITIONS", "3"))
    )
    cfd_max_daily_loss_pct: float = field(
        default_factory=lambda: float(os.getenv("CFD_MAX_DAILY_LOSS_PCT", "0.03"))
    )
    # Deriv's demo account balance is fixed at ~$10,000 with no API to reset
    # it to an arbitrary amount; the user's real intended starting capital
    # is $100. All demo-side risk sizing, drawdown, and performance tracking
    # must use virtual equity rebased onto this number, never the raw demo
    # balance -- see trading.cfd.capital and docs/VISION.md's "Capital
    # model" section.
    cfd_virtual_starting_capital: float = field(
        default_factory=lambda: float(os.getenv("CFD_VIRTUAL_STARTING_CAPITAL", "100.0"))
    )
    cfd_min_stake: float = field(
        default_factory=lambda: float(os.getenv("CFD_MIN_STAKE", "1.0"))
    )
    """Deriv's confirmed live minimum stake for a Multipliers order (see
    scripts/burn_demo_balance.py's MIN_STAKE, discovered the same way).
    Used by CfdRiskManager to SKIP a trade rather than round its
    risk-budgeted stake up past this floor, which would silently risk more
    than risk_per_trade of equity on a small account."""

    # Market Regime Engine (CFD) -- see trading.cfd.regime. ADX's
    # conventional textbook cutoff for "trending" (Wilder's original
    # interpretation); not yet walked through a TRAIN/TEST split the way
    # strategy parameters are -- see docs/ARCHITECTURE_AUDIT.md.
    cfd_regime_adx_window: int = field(
        default_factory=lambda: int(os.getenv("CFD_REGIME_ADX_WINDOW", "14"))
    )
    cfd_regime_trend_threshold: float = field(
        default_factory=lambda: float(os.getenv("CFD_REGIME_TREND_THRESHOLD", "25.0"))
    )

    def is_live_trading_allowed(self) -> bool:
        return self.allow_live_trading and not self.alpaca_paper


settings = Settings()

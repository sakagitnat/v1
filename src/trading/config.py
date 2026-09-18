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
    # OANDA instrument names use an underscore, not a slash (XAU_USD, not
    # XAU/USD). Gold plus the most liquid major pairs to start.
    raw = os.getenv("CFD_INSTRUMENTS", "XAU_USD,EUR_USD,GBP_USD,USD_JPY")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


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

    # CFD/forex (OANDA) -- a separate account, separate safety gate, separate
    # everything from the Alpaca stock system above. See src/trading/cfd/.
    oanda_api_token: str = field(default_factory=lambda: os.getenv("OANDA_API_TOKEN", ""))
    oanda_account_id: str = field(default_factory=lambda: os.getenv("OANDA_ACCOUNT_ID", ""))
    oanda_practice: bool = field(default_factory=lambda: _env_bool("OANDA_PRACTICE", True))
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

    def is_live_trading_allowed(self) -> bool:
        return self.allow_live_trading and not self.alpaca_paper

    def is_cfd_live_trading_allowed(self) -> bool:
        return self.cfd_allow_live_trading and not self.oanda_practice


settings = Settings()

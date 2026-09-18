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
    raw = os.getenv("WATCHLIST", "SPY,AAPL,MSFT,GOOGL,AMZN,NVDA")
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
    bucket_safe_fraction: float = field(
        default_factory=lambda: float(os.getenv("BUCKET_SAFE_FRACTION", "0.5"))
    )

    def is_live_trading_allowed(self) -> bool:
        return self.allow_live_trading and not self.alpaca_paper


settings = Settings()

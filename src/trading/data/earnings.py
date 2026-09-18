from trading.logging_utils import get_logger

logger = get_logger(__name__)


def has_upcoming_earnings(symbol: str, within_days: int = 2) -> bool:
    """True if `symbol` has a scheduled earnings report within the next
    `within_days` calendar days -- used to skip new entries into a stock
    right before it could gap sharply on news, independent of anything the
    price chart shows.

    Best-effort and fails open: if the data isn't available (some ETFs
    like SPY/GLD have no earnings at all) or the lookup errors out, this
    returns False rather than blocking trading on a data hiccup -- a
    missed earnings date is a smaller risk than the whole strategy going
    silently idle because a data source changed its format.
    """
    try:
        import pandas as pd
        import yfinance as yf

        dates = yf.Ticker(symbol).get_earnings_dates(limit=8)
        if dates is None or dates.empty:
            return False

        now = pd.Timestamp.now(tz=dates.index.tz)
        window_end = now + pd.Timedelta(days=within_days)
        return bool(((dates.index >= now) & (dates.index <= window_end)).any())
    except Exception as exc:
        logger.debug("Earnings lookup failed for %s (treating as no upcoming earnings): %s", symbol, exc)
        return False

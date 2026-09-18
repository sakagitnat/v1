import pandas as pd


def load_daily_bars_yfinance(symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
    """Free daily OHLCV bars for backtesting. No API key required."""
    import yfinance as yf

    df = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        return df

    if isinstance(df.columns, pd.MultiIndex):
        # e.g. columns like ("Close", "AAPL") -- keep just the OHLCV field name
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    df.index.name = "date"

    missing = [c for c in ("open", "high", "low", "close", "volume") if c not in df.columns]
    if missing:
        raise ValueError(f"{symbol}: yfinance response is missing columns {missing} (got {list(df.columns)})")

    return df[["open", "high", "low", "close", "volume"]].dropna()


def load_watchlist_bars(symbols: list[str], start: str, end: str | None = None) -> dict[str, pd.DataFrame]:
    return {sym: load_daily_bars_yfinance(sym, start, end) for sym in symbols}

# Automated Stock Trading System

A trend-following, risk-managed trading bot for US-listed stocks, built to run
against [Alpaca](https://alpaca.markets)'s paper (simulated money) trading API
by default, with backtesting on free historical data.

> **Disclaimer — read this first.** No trading system can guarantee profit.
> Markets are risky, past performance does not predict future results, and
> this is not financial advice. This project defaults to **paper trading**
> (simulated money) and requires two explicit, separate settings to be
> changed before it will ever place a real-money order. Do not enable live
> trading until you have reviewed weeks or months of paper-trading results
> and are comfortable with the risk of loss.

## How it works

1. **Strategy** (`src/trading/strategy/trend_momentum.py`) — long-only trend
   following: enter when the 20-day EMA is above the 50-day EMA, price is
   above the 50-day EMA, and RSI(14) is between 40–70 (confirms momentum
   without chasing an overbought move). Exit when the trend flips, or when
   an ATR-based stop-loss / take-profit is hit.
2. **Risk management** (`src/trading/risk/risk_manager.py`) — position size
   is capped so a stopped-out trade only loses `RISK_PER_TRADE` (default 1%)
   of account equity; a hard cap on concurrent open positions
   (`MAX_OPEN_POSITIONS`); a daily-loss circuit breaker
   (`MAX_DAILY_LOSS_PCT`) that halts new entries for the rest of the day.
3. **Backtest engine** (`src/trading/backtest/engine.py`) — replays the
   strategy bar-by-bar over historical data and reports CAGR, Sharpe ratio,
   max drawdown, win rate, and the full trade log.
4. **Execution** (`src/trading/execution/`) — wraps Alpaca's trading API to
   place bracket orders (entry + stop-loss + take-profit) sized by the risk
   manager, using the account's live equity.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Get **paper** API keys from your Alpaca dashboard (Alpaca gives every
account a free paper-trading endpoint) and put them in `.env`:

```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_PAPER=true
```

Edit `WATCHLIST` in `.env` to the symbols you want the strategy to trade
(defaults to SPY, AAPL, MSFT, GOOGL, AMZN, NVDA).

## Backtest first

No API keys needed — pulls free historical data via `yfinance`:

```bash
python scripts/run_backtest.py
```

Prints total return, CAGR, Sharpe ratio, max drawdown, win rate, and trade
count for the configured watchlist since 2020. Tune the strategy's
parameters (EMA windows, RSI bounds, ATR multipliers) and re-run before
risking any money, even simulated money.

## Paper trading

Once you're satisfied with the backtest, run one live evaluation against
your **paper** account:

```bash
python scripts/run_paper_trading.py
```

This checks the latest bar for each watchlist symbol, and opens/closes
paper positions accordingly. Run it once per trading day, shortly after
market open — e.g. via `cron` or a scheduled CI job. It will refuse to run
against real money unless you explicitly set `ALPACA_PAPER=false` **and**
`ALLOW_LIVE_TRADING=true` in the environment (see `.env.example`).

## Tests

```bash
pytest
```

## Project layout

```
src/trading/
  config.py              # environment-driven settings, incl. the live-trading safety switch
  indicators.py           # SMA, EMA, RSI, MACD, ATR
  strategy/
    trend_momentum.py     # default strategy
  risk/
    risk_manager.py        # position sizing, daily-loss circuit breaker
  backtest/
    engine.py              # event-driven backtester
    metrics.py              # CAGR, Sharpe, drawdown, win rate
  data/
    market_data.py          # historical bars via yfinance
  execution/
    broker.py               # Alpaca order placement (paper by default)
    scheduler.py            # one strategy evaluation + order pass
scripts/
  run_backtest.py
  run_paper_trading.py
tests/
```

## Roadmap / going live

This is a starting template, not a finished profitable system. Before ever
setting `ALLOW_LIVE_TRADING=true`:

- Backtest across more symbols, timeframes, and market regimes (bull, bear,
  choppy) — a strategy that only wins in one regime will lose money in
  another.
- Run it on paper for an extended period and compare live paper results to
  the backtest.
- Consider transaction costs, slippage, and taxes, none of which this
  template models.
- Start with real money you can afford to lose, at a small fraction of your
  intended size, and scale up only if results hold up.

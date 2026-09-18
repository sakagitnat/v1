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

1. **Strategies** (`src/trading/strategy/`) — six long-only strategies
   sharing one interface (`prepare()` + `signal_for_row()`), so the backtest
   engine and live execution work with any of them unchanged. The default
   used by both the backtest and the live/paper bot is **`regime_adaptive`**:
   - **`trend_momentum`** — enter when the 20-day EMA is above the 50-day
     EMA, price is above the 50-day EMA, and RSI(14) is 40–70 (momentum
     without chasing an overbought move).
   - **`mean_reversion`** — buy a dip to the lower Bollinger Band confirmed
     by an oversold RSI, sell once price reverts to the average.
   - **`macd_trend`** — MACD crossover, but only taken when price is above
     the 200-day SMA, to filter out whipsaws against the dominant trend.
   - **`breakout`** — classic Donchian-channel/"Turtle Trading" breakout:
     buy a new N-day high, exit on a new M-day low.
   - **`buy_and_hold`** — not a real strategy; a benchmark to check whether
     an active strategy is actually earning its complexity.
   - **`regime_adaptive`** (default) — switches between the sub-strategies
     above based on the broad market's trend (`REGIME_SYMBOL`, SPY by
     default): **bull → breakout**, **bear → mean_reversion**,
     **neutral → macd_trend**. This mapping came out of backtesting all
     five individually across 2020-2026's different market regimes (see
     `compare_strategies.py` below) — breakout had the best risk-adjusted
     returns in trending markets, mean_reversion was the only strategy that
     didn't lose money in the 2022 bear market, and macd_trend is a more
     conservative pick for the turning points between the two.

   All the entry-based strategies (everything but buy-and-hold) exit on an
   ATR-based stop-loss / take-profit in addition to their signal-based exit.
   Swap the `strategy=` argument in `scripts/run_backtest.py` /
   `trading/execution/scheduler.py` to use a single strategy instead.
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

## Comparing strategies across market regimes

```bash
python scripts/compare_strategies.py
```

Backtests all five strategies over 2019-present, then breaks the results
down by period (2020-21 COVID crash/recovery, 2022 bear market, 2023-24
recovery, 2025-present, and the full span) so you can see which strategy
held up best in which kind of market -- a strategy that wins over the full
span can still be the worst performer in a bear market, and this is where
that shows up. Also runnable on demand via the **Compare Strategies**
GitHub Actions workflow.

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

## Running it automatically (GitHub Actions)

Two workflows in `.github/workflows/` run this without you having to keep a
computer on:

- **`daily-trading.yml`** — runs `scripts/run_paper_trading.py` on a
  schedule (weekdays, shortly after US market open). Fully automatic.
- **`manual-command.yml`** — a `workflow_dispatch` you (or Claude, on your
  behalf, when you ask in chat) can trigger anytime to check status,
  pause/resume the daily bot, or place a one-off buy/sell. Runs
  `scripts/cli.py` with whatever command you give it.

Both are hardcoded to `ALPACA_PAPER=true`, so neither can place a live order
even by accident, regardless of what's in your secrets.

**One-time setup, on GitHub.com** (this step can't be done for you — it
needs your own Alpaca keys, which should never be pasted into chat or
committed to the repo):

1. Go to the repo → **Settings → Secrets and variables → Actions**.
2. Add two repository secrets: `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`,
   using your **paper** account's keys from the Alpaca dashboard.
3. That's it — the daily workflow will start running on its own schedule,
   and you can trigger the manual one anytime (via the Actions tab, or by
   asking in chat).

### Pausing/resuming

`state/bot_state.json` holds a single `paused` flag that the daily workflow
checks before trading. `python scripts/cli.py pause` / `resume` (run
locally, or via the manual-command workflow) flips it; the manual workflow
commits the change back to the repo automatically.

## Tests

```bash
pytest
```

## Project layout

```
src/trading/
  config.py              # environment-driven settings, incl. the live-trading safety switch
  indicators.py           # SMA, EMA, RSI, MACD, ATR, Bollinger Bands, Donchian channel
  regime.py                # bull/bear/neutral classifier used by regime_adaptive
  strategy/
    trend_momentum.py     # EMA cross + RSI filter
    mean_reversion.py      # Bollinger Band dip-buy
    macd_trend.py           # MACD cross filtered by 200-day trend
    breakout.py              # Donchian channel / Turtle-style breakout
    buy_and_hold.py           # benchmark, not a real strategy
    regime_adaptive.py        # switches between the above by market regime (default)
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
    state.py                # paused/resumed flag shared with the daily workflow
scripts/
  run_backtest.py
  compare_strategies.py       # all strategies x several market regimes
  run_paper_trading.py         # used by the daily-trading.yml workflow
  cli.py                        # status / pause / resume / buy / sell -- used by manual-command.yml
.github/workflows/
  daily-trading.yml
  manual-command.yml
  backtest.yml
  compare-strategies.yml
state/
  bot_state.json
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

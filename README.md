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
   used by both the backtest and the live/paper bot is **`breakout`**:
   - **`breakout`** (default) — classic Donchian-channel/"Turtle Trading"
     breakout: buy a new N-day high, exit on a new M-day low. Parameters
     tuned by `optimize_strategy.py --objective calmar` for the most total
     profit per unit of max drawdown, not for win rate -- see that file's
     docstring and `breakout.py`'s for the numbers.
   - **`trend_momentum`** — enter when the 20-day EMA is above the 50-day
     EMA, price is above the 50-day EMA, and RSI(14) is 40–70 (momentum
     without chasing an overbought move).
   - **`mean_reversion`** — buy a dip to the lower Bollinger Band confirmed
     by an oversold RSI, sell once price reverts to the average.
   - **`macd_trend`** — MACD crossover, but only taken when price is above
     the 200-day SMA, to filter out whipsaws against the dominant trend.
   - **`buy_and_hold`** — not a real strategy; a benchmark to check whether
     an active strategy is actually earning its complexity.
   - **`regime_adaptive`** — switches between breakout/mean_reversion/
     macd_trend based on the broad market's trend (`REGIME_SYMBOL`, SPY by
     default: bull → breakout, bear → mean_reversion, neutral → macd_trend).
     Tried as the default first, but a full 2020-present comparison (see
     `compare_strategies.py`) showed plain `breakout` alone beating it on
     CAGR, Sharpe, *and* max drawdown simultaneously once breakout itself
     was tuned -- the extra complexity of switching wasn't earning its
     keep, so it was dropped back to an available-but-not-default option.

   All the entry-based strategies (everything but buy-and-hold) exit on an
   ATR-based stop-loss / take-profit in addition to their signal-based exit.
   Swap the `strategy=` argument in `scripts/run_backtest.py` /
   `trading/execution/scheduler.py` to use a different one.
2. **Risk management** (`src/trading/risk/risk_manager.py`) — position size
   is capped so a stopped-out trade only loses `RISK_PER_TRADE` (default 1%)
   of account equity; a hard cap on concurrent open positions
   (`MAX_OPEN_POSITIONS`); a daily-loss circuit breaker
   (`MAX_DAILY_LOSS_PCT`) that halts new entries for the rest of the day.
3. **Backtest engine** (`src/trading/backtest/engine.py`) — replays the
   strategy bar-by-bar over historical data and reports CAGR, Sharpe ratio,
   max drawdown, win rate, and the full trade log.
4. **Execution** (`src/trading/execution/`) — wraps Alpaca's trading API.
   Buys are **notional** (a dollar amount, not a share count), sized by the
   risk manager, so small accounts can hold fractional shares of expensive
   stocks. Alpaca doesn't support bracket orders (built-in stop-loss +
   take-profit) for fractional quantities, so each entry is followed by two
   independent DAY orders for the exact filled quantity -- a stop and a
   limit -- which `positions.py` tracks and the scheduler re-arms every run
   (cancelling and resubmitting) so protection stays live intraday each
   trading day, not just the day it opened.

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

Backtests all six strategies over 2019-present, then breaks the results
down by period (2020-21 COVID crash/recovery, 2022 bear market, 2023-24
recovery, 2025-present, and the full span) so you can see which strategy
held up best in which kind of market -- a strategy that wins over the full
span can still be the worst performer in a bear market, and this is where
that shows up. Also runnable on demand via the **Compare Strategies**
GitHub Actions workflow.

## Tuning a strategy's parameters

```bash
python scripts/optimize_strategy.py --strategy breakout --objective calmar
python scripts/optimize_strategy.py --strategy breakout --objective win_rate
```

Grid-searches a strategy's parameters on a 2019-2023 TRAIN period, then
validates the winning combination once against a 2024-present TEST period
it never touched during the search -- a combination that only looks good
because it's curve-fit to TRAIN gets flagged as overfit here, not shipped.
Two objectives:
- **`calmar`** (default) -- the most total profit per unit of max drawdown;
  rejects any combination whose drawdown breaches -25%, regardless of its
  return. This is what picked `breakout`'s current defaults.
- **`win_rate`** -- the highest fraction of winning trades among
  combinations that keep TRAIN CAGR positive. Trades average win size for
  consistency; a strategy optimized this way will win more often but make
  less per win. Also runnable via the **Optimize Strategy** GitHub Actions
  workflow (pick the strategy and objective as inputs).

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

`state/bot_state.json` holds a `paused` flag that the daily workflow
checks before trading. `python scripts/cli.py pause` / `resume` (run
locally, or via the manual-command workflow) flips it; the manual workflow
commits the change back to the repo automatically.

### Capital floor + risk ladder (protecting the original principal)

```bash
python scripts/cli.py set-floor 100    # e.g. "never trade below my starting $100"
python scripts/cli.py clear-floor
```

When a floor is set, the live bot:
- **Stops opening new positions** while equity is at or below it (existing
  positions still close normally on their own stop-loss/target).
- **Scales risk per trade** by how big a cushion equity has above the floor
  (`RiskManager.effective_risk_per_trade`): half the configured
  `RISK_PER_TRADE` while the cushion is under 20%, the full amount between
  20-50%, and 1.5x once the cushion exceeds 50% -- trading more of the
  profit built up, not more of the original principal.
- **Ratchets the floor up as equity grows** (`risk/ratchet.py`): once
  equity is `RATCHET_TRIGGER_PCT` (default 20%) above the current floor,
  the floor rises by `RATCHET_BANK_FRACTION` (default 50%) of that excess
  -- "banking" part of each gain as a new, higher protected minimum, so
  profit already made becomes progressively harder to trade away. The
  first floor ever set is remembered as `initial_floor`; `cli.py status`
  reports `capital_floor - initial_floor` as banked profit.

This protects money *within* the trading account -- it does not withdraw
anything to a bank account. That's a separate, manual, real-money-only
step (see below). It's also a strong protection, not an absolute
guarantee: an overnight gap past a stop-loss can still land below the
floor in one move, since a stop-loss order fills at the next available
price, not necessarily its trigger price.

**Turning banked profit into money you can actually spend** needs a live
(not paper) Alpaca account funded with real money, plus a bank transfer
out -- both real-money steps this project deliberately does not automate.
When paper trading has proven the strategy out and you're ready to go
live, do that funding/withdrawal through Alpaca's own dashboard, or ask
in chat and it'll walk through it with you rather than trigger a transfer
on its own; moving money out of a brokerage account should always be a
step you take knowingly, not something a bot decides for you.

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
    breakout.py              # Donchian channel / Turtle-style breakout (default)
    trend_momentum.py     # EMA cross + RSI filter
    mean_reversion.py      # Bollinger Band dip-buy
    macd_trend.py           # MACD cross filtered by 200-day trend
    buy_and_hold.py           # benchmark, not a real strategy
    regime_adaptive.py        # switches between the sub-strategies by market regime (available, not default)
  risk/
    risk_manager.py        # position sizing, daily-loss circuit breaker
  backtest/
    engine.py              # event-driven backtester
    metrics.py              # CAGR, Sharpe, drawdown, win rate
  data/
    market_data.py          # historical bars via yfinance
  execution/
    broker.py               # Alpaca order placement (paper by default), notional buys + stop/limit orders
    scheduler.py            # one strategy evaluation + order pass
    state.py                # paused flag + capital floor, shared with the daily workflow
    positions.py             # tracked stop/target prices for open fractional positions
scripts/
  run_backtest.py
  compare_strategies.py       # all strategies x several market regimes
  optimize_strategy.py         # train/test parameter grid search (calmar or win_rate)
  run_paper_trading.py          # used by the daily-trading.yml workflow
  cli.py                         # status / pause / resume / buy / sell -- used by manual-command.yml
.github/workflows/
  daily-trading.yml
  manual-command.yml
  backtest.yml
  compare-strategies.yml
  optimize-strategy.yml
state/
  bot_state.json
  positions.json
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

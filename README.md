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
   (`MAX_DAILY_LOSS_PCT`) that halts new entries for the rest of the day;
   an **earnings-date filter** (`src/trading/data/earnings.py`) that skips
   opening a *new* position in a stock with an earnings report due in the
   next 2 days -- a single-company announcement can gap the price well past
   the ATR-based stop, which the stop can't protect against overnight. This
   only blocks new entries; it doesn't close positions already open going
   into an earnings date. It's best-effort: if the earnings-date lookup
   fails or the data isn't available (index ETFs like SPY/GLD have no
   earnings at all), it fails open rather than blocking trading on a data
   hiccup.
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
(defaults to SPY, AAPL, MSFT, GOOGL, AMZN, NVDA, GLD -- GLD is the SPDR
Gold Shares ETF, trading like any other equity, so it needs no special
commodities access).

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
checks before trading. `python scripts/cli.py pause [--reason "..."]` /
`resume` (run locally, or via the manual-command workflow) flips it; the
manual workflow commits the change back to the repo automatically. The
reason (if given) is stored as `pause_reason` and shown by `cli.py status`
while paused, so it's clear later why trading was halted.

### Excluding a symbol from new entries

```bash
python scripts/cli.py exclude-symbol TSLA --reason "CEO scandal breaking"
python scripts/cli.py include-symbol TSLA
```

Blocks *new* entries into that symbol (any position already open in it is
left alone -- its stop/target keep managing the exit as normal) until
explicitly re-included. This is the manual, judgment-based counterpart to
the automatic `has_upcoming_earnings` check above -- for news too fresh or
too specific for a mechanical rule to catch. Claude uses this (via the
manual-command workflow) when asked to react to breaking news about a
specific holding, or on its own initiative within a narrow, reversible
scope -- see "Ongoing news monitoring" below.

### Ongoing news monitoring

Beyond the mechanical `has_upcoming_earnings` check, Claude periodically
checks broader news (per-symbol and macro) on its own and acts within a
narrow, reversible scope you've authorized:
- **excluding a single symbol** from new entries (never closes an existing
  position) when it finds material, fresh news about that company --
  earnings surprise, guidance cut, lawsuit, executive scandal, etc.
- **pausing the whole bot** (new entries only, same as above) for
  macro/systemic risk -- e.g. an unscheduled Fed action, a geopolitical
  shock.

Both are undone (`include-symbol` / `resume`) once Claude judges the
concern has passed, checked again at the next scheduled run. This is
paper trading only, reversible, and scoped to *not opening new positions*
-- it never closes a position, changes risk sizing, or touches real
money.

**Schedule.** The daily trading run fires at 15:00 UTC on weekdays. That
specific time isn't arbitrary: US market open is always 9:30 ET, but
9:30 ET is a different UTC time depending on whether US daylight saving
is in effect (13:30 UTC vs 14:30 UTC), and GitHub Actions cron doesn't
shift for DST on its own. 15:00 UTC sits safely after either case
year-round, so it never needs manual adjustment twice a year. The news
check runs at 13:42 UTC -- about 75 minutes earlier -- to leave enough
slack for the search-and-decide step plus the manual-command workflow's
own commit-back-to-the-repo step to land *before* the trading run reads
`state/bot_state.json` at 15:00. (The odd `:42` minute, rather than a
round `:00`/`:30`, is just to avoid every scheduled job on the platform
landing on the same instant -- no significance to the number itself.)

**How it runs, and its limits.** Set up as a recurring Routine bound to
the chat session that set it up, so it reuses that session's
already-authorized GitHub access rather than needing to re-request it
fresh every firing (a *fresh*-session Routine would have no GitHub tools
at all, which was tried first and doesn't work). Two consequences of that
choice:
- Routines on this platform auto-expire after 7 days regardless of type,
  so this one needs to be periodically recreated to keep running --
  Claude will flag it on what looks like the last scheduled firing.
- Session-bound Routines don't get the platform's own automatic
  push/email notification (that only exists for fresh-session Routines).
  So each firing that takes an action, or finds something concerning
  enough to flag even without acting, explicitly sends a phone/desktop
  push notification -- a firing that finds nothing notable just leaves a
  short note in the chat instead, without pinging you.

Ask in chat anytime to check the news yourself on demand, change the
schedule, recreate it, or turn it off.

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

### Bucket mode (safe + risk, once you're well past the "withdraw" milestone)

Two fixed checkpoints, both multiples of the initial floor (e.g. $100):

1. **`WITHDRAWAL_MULTIPLE`** (default 2.0 -> $200) -- "principal back plus a
   first $100 of usable profit." The capital floor ratchets up toward this
   as normal (banking profit -- see above) but never past it; once
   reached, the floor **locks there for good** instead of continuing to
   climb. This is money conceptually earmarked to withdraw, not something
   that keeps growing on its own.
2. **`BUCKET_ACTIVATION_MULTIPLE`** (default 3.0 -> $300) -- once equity
   first exceeds this, the floor is snapped to exactly the $200 checkpoint
   (even if gradual ratcheting hadn't quite reached it yet) and the live
   bot permanently switches from one strategy trading the whole account to
   **buckets** (`src/trading/execution/buckets.py`, `state/buckets.json`),
   each sized off its own virtual cash instead of total equity. In the
   example, that's the $100 between $200 and $300 that starts getting
   managed this way -- more precisely, everything above the now-frozen
   $200 floor, however much that turns out to be by the time $300 is hit.

The buckets themselves:
- **`safe`** -- Mean Reversion, at half the configured `RISK_PER_TRADE`.
  Historically the strategy that best avoided losses in a bad market (see
  "Comparing strategies" above).
- **`risk1`** -- Breakout (the same calmar-tuned strategy the bot already
  uses), at the full `RISK_PER_TRADE`, aimed at maximum profit. Add more
  `riskN` buckets later by adding entries to `state/buckets.json` (or ask
  in chat) -- `buckets.rebalance()` already splits the shared risk pool
  across however many there are.

Each run, `growth_capital` (equity above the now-frozen $200 floor) is
split `BUCKET_SAFE_FRACTION` (default 50%) to the safe bucket and the rest
across risk buckets, but a bucket's cash only ever gets topped up toward
that target -- it's never clawed back; a bucket only loses cash through
its own trading losses. If a risk bucket's cash drops below $5 ("blown"),
it stops opening new positions until profit from other risk buckets --
or new growth -- refills it, ahead of any bucket that's still healthy.
This is a simplified accounting model (it compares bucket cash, not the
current value of what a bucket has invested, so it can be imprecise while
positions are open); Alpaca's own buying power is the backstop that keeps
that imprecision safe rather than an actual overspend.

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
    ratchet.py               # banks profit by raising the capital floor as equity grows
  backtest/
    engine.py              # event-driven backtester
    metrics.py              # CAGR, Sharpe, drawdown, win rate
  data/
    market_data.py          # historical bars via yfinance
  execution/
    broker.py               # Alpaca order placement (paper by default), notional buys + stop/limit orders
    scheduler.py            # one strategy evaluation + order pass; single-strategy or bucket mode
    state.py                # paused flag, capital floor, milestone flag -- shared with the daily workflow
    positions.py             # tracked stop/target prices (+ owning bucket) for open fractional positions
    buckets.py                # safe/risk virtual sub-accounts, active once the withdrawal milestone hits
scripts/
  run_backtest.py
  compare_strategies.py       # all strategies x several market regimes
  optimize_strategy.py         # train/test parameter grid search (calmar or win_rate)
  run_paper_trading.py          # used by the daily-trading.yml workflow
  cli.py                         # status / pause / resume / buy / sell / set-floor / cancel -- used by manual-command.yml
.github/workflows/
  daily-trading.yml
  manual-command.yml
  backtest.yml
  compare-strategies.yml
  optimize-strategy.yml
state/
  bot_state.json
  positions.json
  buckets.json
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

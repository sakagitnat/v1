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

**The CFD/Deriv system below (see "CFD/forex trading (Deriv)") is being
developed toward a larger goal: an AI Trading Manager, not a
single-strategy bot.** See `docs/VISION.md` for that master vision and
`docs/ARCHITECTURE_AUDIT.md` for what already exists vs. what's still
missing.

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
- **Stops opening new positions** once equity is genuinely *below* it
  (existing positions still close normally on their own stop-loss/target).
  Equity sitting exactly *at* the floor still trades -- deliberately, since
  the floor is normally first set equal to the current balance ("protect
  my starting $100"), and blocking trades at that exact point would
  deadlock forever: equity could never rise above a floor it's never
  allowed to trade away from.
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

## CFD/forex trading (Deriv)

A second, completely separate trading system, in `src/trading/cfd/` --
different account, different broker, different everything from the stock
system above. Built because the stock system (Alpaca, US equities) can't
do genuine intraday day-trading on a small account: the US Pattern Day
Trader (PDT) rule caps accounts under $25,000 to 3 same-day round trips
per 5 business days on a margin account. Forex/CFDs aren't "securities"
under that rule, so they aren't PDT-restricted at all.

**Broker: Deriv**, after two dead ends:
- **XM** (MetaTrader-only) needs either a desktop MT4/5 terminal running
  continuously (not practical on GitHub Actions) or a paid third-party
  bridge (tried MetaApi.cloud; its dashboard only offered a paid
  ~$9/month "Cloud-g2" account for MT5, no reachable free tier).
- **OANDA** has a free REST API (v20) in principle, but the OANDA
  division reachable from a Thailand signup ("OANDA Global Markets")
  doesn't support it at all -- MetaTrader only, same problem as XM.

Deriv has its own free WebSocket API directly, reachable from a Thailand
signup, no bridge and no per-hour charges. One important wrinkle: Deriv's
demo signup creates *two* accounts -- an MT5-branded "CFDs" one (which the
API can't control, same MetaTrader problem as above) and a native
"Options" one (which it can). Use the native account's token.

Trades **Multipliers**, not traditional leveraged CFDs -- Deriv's own
product that caps maximum loss at the stake, unlike a plain leveraged
position where a big enough adverse move can lose more than the margin
put up.

**Setup:**
1. Free demo account: https://deriv.com -- use the native **"Options"**
   demo account it creates automatically, not the MT5-branded "CFDs" one
2. https://app.deriv.com/account/api-token -> select the Options account
   -> check the **Trade** scope -> set an expiry (max 90 days -- Deriv
   requires one; re-generate before it lapses) -> Create token
3. Add `DERIV_API_TOKEN` as a repository secret (same as the Alpaca keys
   -- never paste it in chat)

No separate account ID needed *from you*: `broker.py` discovers it itself
(`GET {OPTIONS_API_BASE}/accounts` with the token) as part of connecting.
`DERIV_APP_ID` must be a **registered application's ID**, not the shared
public `1089` -- that shared ID only works against Deriv's classic
WebSocket API, and returns "Invalid application" (401) against the newer
`/trading/v1/options` REST API this system uses. Register one (free, no
approval wait) at https://developers.deriv.com -> "Register new
application" -> **Native apps** (tagged `PAT`, matching the PAT-style
tokens this system uses) -> any name without "Binary"/"Deriv" in it,
0% markup, no website URL needed. The resulting App ID is not secret
(like an OAuth client_id) -- safe to paste directly.

**Connection flow is not the classic one most Deriv API examples show.**
The commonly-documented `wss://ws.derivws.com/websockets/v3` +
`{"authorize": token}` approach doesn't work with PAT-style tokens (the
`pat_...` prefix the current account/api-token page issues) -- every
token tried returned "The token is invalid" from that endpoint, confirmed
with Deriv support to be a wrong-flow issue, not an account problem.
The actual PAT flow (`broker.py`'s `connect()`): `GET
{OPTIONS_API_BASE}/accounts` (Bearer token + `Deriv-App-ID` header) to
find the account and check `account_type`, then `POST
{OPTIONS_API_BASE}/accounts/{id}/otp` (same headers) for a short-lived,
single-use one-time-password and a ready-to-use WebSocket URL with it
attached -- connecting to *that* URL is already authenticated, no
separate `authorize` message needed. Despite "options" in the URL path,
Deriv support confirmed Multipliers contracts use this same flow (it's
the name of the whole newer API surface, not a restriction to binary
options) -- but MT5 leveraged forex/CFDs is a different product and must
not use this endpoint.

A token can authorize more than one account at once -- Deriv creates an
unverified real-money account for every signup automatically, alongside
any demo account, even for users who only ever use demo. `connect()`
picks the account whose `account_type` is `"demo"` explicitly (or
`"real"` if `CFD_ALLOW_LIVE_TRADING` is set), rather than assuming
`accounts[0]` is the right one.

**How it works:** `src/trading/cfd/strategy.py`'s `EmaCrossoverStrategy`
(fast/slow EMA crossover, long or short, ATR-based stop/target) runs on
**hourly (H1)** candles -- not the originally-intended 15-minute bars;
see "Backtesting" below for why. Deriv prices stop-loss/take-profit as
dollar P&L *amounts*, not price levels the way Alpaca/OANDA do, so
`risk.py`'s `stake_and_limits()` converts the strategy's ATR-based price
distance into a (stake, stop_loss_amount, take_profit_amount) triple
sized so a stop-out loses about `CFD_RISK_PER_TRADE` of equity,
regardless of the instrument's price scale. `.github/workflows/
cfd-trading.yml` triggers a run roughly hourly on weekdays via
`scripts/run_cfd_trading.py`, without needing an always-on server
(GitHub Actions minutes are free for periodic runs like this).

Default instruments: `frxXAUUSD` (gold) plus `frxEURUSD`, `frxGBPUSD`,
`frxUSDJPY` -- change via `CFD_INSTRUMENTS` (Deriv's own mixed-case,
case-sensitive symbol names). Manual control (`scripts/cfd_cli.py status`
/ `performance` / `pause` / `resume` / `exclude-instrument` /
`include-instrument`, or the "CFD Manual Command" GitHub Actions
workflow) mirrors the stock system's `cli.py`.

**Capital model: virtual equity (demo).** Deriv's demo signup fixes the
account balance at a **fixed ~$10,000, with no API to reset it to an
arbitrary amount** -- but the real capital this system is meant for is
**$100**. Sizing trades off the raw $10,000 demo balance would make every
position ~100x larger than what a real $100 account could ever risk. So
on a demo account, every risk/performance calculation is computed from a
**virtual equity** (`trading/cfd/capital.py`) instead: the first time the
bot ever runs, it records the broker's balance as a baseline
(`broker_baseline`, in `state/cfd_bot_state.json`); from then on,
`virtual_equity = CFD_VIRTUAL_STARTING_CAPITAL (default 100) +
(broker_balance - broker_baseline)` -- so a $10 gain on the real $10,000
balance shows up as a $10 gain on the $100 virtual one, exactly mirroring
real P&L, never the raw balance itself. `cfd_cli.py status` prints both
the raw broker balance and the virtual equity, labeled, so it's always
clear which is which. Real (non-demo) accounts are unaffected -- real
money is never rebased, it already is what it is.

One consequence: if Deriv's minimum order size for an instrument would
force a stake bigger than `CFD_RISK_PER_TRADE` of a small (e.g. $100)
virtual account allows, `CfdRiskManager.stake_and_limits()` **skips the
trade** rather than rounding the stake up past the configured risk --
see `risk.py`'s `min_stake` (`CFD_MIN_STAKE`, default $1.00, Deriv's
confirmed live minimum).

(This replaces an earlier, deliberately-deprecated approach,
`scripts/burn_demo_balance.py`, which tried to solve the same $10,000-vs-
$100 mismatch by actually trading the demo balance down. That directly
conflicts with this project's rule against deliberately trading a
balance down or up to hit a target number -- see `docs/VISION.md` -- so
it's kept only as documented history and refuses to run without an
explicit override flag.)

**Capital floor (opt-in, not automatic) and the daily-loss breaker
(persisted, not per-run).** Two corrections made 2026-09-19 after a
second, independent code review caught them:

- `capital_floor` is **never set automatically**. An earlier version set
  it to the exact starting virtual equity ($100) on the very first run --
  but on a small account, one ordinary loss (e.g. -$1 at 1% risk) drops
  equity below a floor set that tight, and with no way to adjust it, new
  entries stayed blocked *forever*. `cfd_cli.py set-floor AMOUNT` /
  `clear-floor` are now the only way a floor gets applied -- pick a
  number with real cushion below your current virtual equity, not equal
  to it. `status`'s "Growth since virtual start" line no longer depends
  on a floor ever having been set -- it's computed directly from
  `CFD_VIRTUAL_STARTING_CAPITAL`, which is always known.
- The daily-loss circuit breaker (`CFD_MAX_DAILY_LOSS_PCT`) now actually
  tracks loss across a real calendar day. `CfdRiskManager`'s start-of-day
  equity and halted flag used to live only in memory, and a fresh
  `CfdRiskManager` gets constructed every scheduler run (a new process
  each time, on GitHub Actions) -- so the breaker silently reset every
  ~hour and could never accumulate a full day's loss. `trading.cfd.state.
  get_daily_risk_tracking`/`set_daily_risk_tracking` now persist both
  values, keyed to the current UTC date, and `scheduler.py` feeds them
  into `CfdRiskManager` explicitly each run.

**Strategy Registry & lifecycle.** Every CFD strategy is a registered
`name@version` tracked through the lifecycle `docs/VISION.md` defines --
`RESEARCH -> CANDIDATE -> VALIDATED -> PAPER -> ACTIVE -> PAUSED ->
RETIRED` (`trading/cfd/strategy_registry.py`, persisted to
`state/cfd_strategy_registry.json`). The live scheduler no longer
hardcodes which strategy it trades: each run it asks the registry for
whichever single strategy is marked `ACTIVE` and refuses to guess if zero
or more than one are (a real misconfiguration, not something to trade
through silently). `scripts/seed_strategy_registry.py` seeded the
strategies that already existed in code: `ema_crossover@v1` went straight
into `ACTIVE` (grandfathered -- it was already the live strategy, backed
by the real TRAIN/TEST validation in "Backtesting" below, just predating
this registry). `donchian_breakout@v1` (placeholder, never-validated
params) was initially seeded as `CANDIDATE` -- but the actually-validated
params a real grid search found (`entry_window=80`, TRAIN cagr=7.9%,
TEST cagr=9.8%, agreeing in sign and magnitude -- see "Backtesting"
below) were never registered at all, an oversight only caught by a
second, independent code review on 2026-09-19. Fixed the same day:
`donchian_breakout@v2` now carries those actually-validated params as
`VALIDATED`, and `v1` is `RETIRED` (superseded, not deleted -- the audit
trail stays intact). Every *later* transition goes through `cfd_cli.py promote-strategy NAME
VERSION STATE --reason "..."`, which enforces the pipeline order (one
stage forward at a time -- no skipping straight to `ACTIVE`) and requires
a stated reason, logged in the entry's audit trail
(`cfd_cli.py list-strategies` to see it). This registry doesn't yet
include the actual validation pipeline that's meant to gate each
promotion (walk-forward, Monte Carlo/stress test, real paper trading) --
promotion today is a deliberate manual, audited action, not an automatic
gate; see `docs/ARCHITECTURE_AUDIT.md`'s later phases for that.

**Market Regime Engine & Strategy Selector.** Each run, every instrument's
own current candles (not a single reference symbol the way the stock
system's `trading/regime.py` uses SPY -- there's no equivalent single
"the market" reference across forex pairs, gold, and Deriv's synthetic
indices) are classified as `trending`, `ranging`, or `unknown`
(`trading/cfd/regime.py`, via ADX -- the same trend-strength indicator
`EmaCrossoverStrategy`'s own optional chop filter already uses).
`trading/cfd/selector.py` matches that regime against every `ACTIVE`
registered strategy's `suited_regimes` and picks the one that fits --
**no match is an explicit NO TRADE, logged and skipped, not a fallback
guess.** Both registered strategies (`ema_crossover`, `donchian_breakout`)
are trend-following and tagged `suited_regimes=["trending"]`, so today
this mostly acts as a gate that skips new entries during a `ranging`
market -- there's no mean-reversion/range strategy registered yet to
trade that regime instead (see `docs/ARCHITECTURE_AUDIT.md`).
`trading.cfd.strategy_registry.set_state()`/`register()` enforce **at
most one `ACTIVE` strategy per regime** at promotion time, so the
selector's match is never ambiguous. An already-open position is always
managed to its exit by the *exact* strategy version that opened it
(tagged in its trade metadata), never whatever happens to be `ACTIVE` by
the time it closes -- so promoting or pausing a strategy can never
retroactively change how an existing position gets closed out.

**Failure Analysis.** `trading/cfd/failure_analysis.py`
(`cfd_cli.py failures`) reads the Trade Database and classifies every
losing trade as `normal_statistical_loss` (lost about its budgeted
`risk_amount` -- the ordinary cost of the edge), `excessive_risk` (lost
notably more than budgeted -- a gap, slippage, or sizing issue), or
`regime_mismatch` (the regime recorded at entry wasn't in the strategy's
`suited_regimes` -- only possible for a trade predating the Strategy
Selector's regime gate). It also flags **strategy degradation**: a
registered strategy whose most recent trades' expectancy has fallen
sharply versus its own earlier history. Three of the vision's loss
categories -- abnormal market/news event, execution problem, data
problem -- are **never guessed at**: this project doesn't capture the
news, latency, or data-quality signals they'd need, so a trade that might
be one of those is classified `normal_statistical_loss` rather than a
fabricated specific cause (see `docs/ARCHITECTURE_AUDIT.md`). A
degradation flag is a prompt to look, never an automatic pause -- acting
on it still goes through `cfd_cli.py promote-strategy ... PAUSED` like
every other lifecycle change.

**Validation: Walk-Forward + Monte Carlo.** `trading/cfd/validation.py`
adds the two checks docs/VISION.md's pipeline calls for beyond the
TRAIN/TEST split `optimize_cfd_strategy.py`/`optimize_cfd_breakout.py`
already do. **Walk-forward** (`run_walk_forward`) splits the TEST period
into several sequential, non-overlapping folds and re-runs the backtest
on each with the *same fixed params* (it doesn't re-optimize per fold --
that would multiply the grid search's runtime by the fold count; it
checks whether already-chosen params keep working across time, not what
the best re-tuning per period would have been), reporting how many folds
were profitable and the worst single fold's drawdown. **Monte Carlo**
(`run_monte_carlo`) reshuffles a backtest's own realized trade P&Ls into
thousands of random orders, to see whether the result depended on a
lucky sequence, and reports a probability-of-ruin estimate (the fraction
of simulated paths that ever dropped to half of starting equity) plus
percentiles of final equity and max drawdown. Both are pure functions
over data a backtest already produces -- no new market data or API calls.

**Research Lab.** `trading/cfd/research_lab.py` (`scripts/
research_cfd_strategy.py`) automates running a strategy's parameter grid
through the *entire* pipeline -- Backtest -> Out-of-Sample -> Walk-Forward
-> Monte Carlo -- and auto-registers any candidate that clears every gate
into the Strategy Registry as `VALIDATED`, **never higher**: the
remaining steps (Paper Trading, then Promote) still need a human's
explicit `promote-strategy` call, per docs/VISION.md's rule against
promoting a strategy on backtest results alone. This doesn't invent new
strategy logic -- "candidate" means a new, systematically-searched
parameter set for an *existing* strategy class, the same grid search
`optimize_cfd_breakout.py` already does by hand; what's new is that a
passing result gets registered automatically, audit trail and all,
instead of a human reading a printed table and typing the registration
command themselves. Run via the "CFD Manual Command" workflow's
`research-strategy` command.

**Operating Modes.** `trading/cfd/operating_mode.py`
(`cfd_cli.py set-mode {defensive,normal,aggressive,recovery}`) scales
`risk_per_trade` and `max_open_positions` by a fixed, pre-approved
multiplier per mode -- never whether the bot trades at all (`pause`/
`resume` still covers that). `defensive` and `recovery` deliberately use
the *same* conservative 0.5x multiplier: Recovery means "trade smaller
because equity is under strain," never "trade bigger to catch up on
losses faster" -- the latter is exactly the revenge-trading/martingale
pattern docs/VISION.md forbids outright. They're kept as distinct,
separately-loggable states so *why* the bot is being cautious stays
visible, even though the numeric effect is identical today. `aggressive`
(1.5x) is still capped by `CFD_MAX_RISK_PER_TRADE_CEILING` -- an absolute
ceiling no mode may ever cross, regardless of `CFD_RISK_PER_TRADE` or
which mode is set.

**Paper Trading.** `trading/cfd/paper_trading.py` runs every strategy
sitting in the Strategy Registry's `PAPER` state through the same
regime-gated Strategy Selector logic as `ACTIVE` strategies, on the same
real-time candles the live scheduler already fetched -- but never places
a real (or demo-account) Deriv order. A paper position's stop/target are
checked against each new candle's high/low locally (the same no-slippage
exact-fill logic `CfdBacktestEngine` uses for a historical backtest,
just run incrementally live instead of once over history, since there's
no real broker managing a paper position's stop-loss/take-profit). Each
`PAPER` strategy tracks its own independent virtual equity, seeded at
`CFD_VIRTUAL_STARTING_CAPITAL`, and its results land in a **separate**
log (`state/cfd_paper_trades.jsonl`, `cfd_cli.py paper-performance`) --
never mixed with the real Trade Database. This is genuinely the
"Paper Trading" pipeline stage docs/VISION.md calls for -- real
forward-looking validation on data no backtest ever saw, between
automated validation (Research Lab, which only ever lands a candidate at
`VALIDATED`) and a human's decision to promote to `ACTIVE`.

**AI Trading Manager: Management Report.** `trading/cfd/manager_report.py`
(`cfd_cli.py manager-report`) is the layer that actually ties Phases 0-4
together: it reads the Trade Database, the Paper Trading log, and the
Strategy Registry, and produces a consolidated report -- overall
performance, the loss breakdown, every strategy grouped by lifecycle
state, and **concrete, copy-pasteable recommended commands** (e.g. "this
`ACTIVE` strategy shows degradation, run `promote-strategy ... PAUSED`",
"this `VALIDATED` candidate is ready to start paper trading, run
`promote-strategy ... PAPER`", "this `PAPER` strategy has 25 trades and a
positive expectancy, worth reviewing for `ACTIVE`"). **It never applies
any of these itself.** Every lifecycle change still goes through the
same deliberate, audited `promote-strategy` call as any other manual
change -- handing an AI unrestricted authority to pause/promote
strategies on its own would be exactly the AI-overrides-the-Risk-Governor
/ hot-edit-without-validation behavior docs/VISION.md forbids. What *is*
already fully automated, per the vision, is the AI choosing BUY/SELL/NO
TRADE and selecting among already-`ACTIVE` strategies each run (see
"Market Regime Engine & Strategy Selector" above) -- the distinction
this report is built to respect is between deciding *how to trade with
what's already approved* (automatic) and deciding *what gets approved*
(always a human).

**Trade Database & Performance Engine.** Every trade the live bot closes
-- whether by its own signal-exit logic or by Deriv auto-closing a
stop-loss/take-profit between runs -- is logged to
`state/cfd_trades.jsonl` (`trading/cfd/trade_log.py`), all money fields
in virtual-equity terms. `scripts/cfd_cli.py performance`
(`trading/cfd/performance.py`) computes net return, expectancy, profit
factor, win rate, average win/loss, average R multiple, Sharpe, Sortino,
Calmar, max drawdown, longest losing streak, and breakdowns by strategy/
regime/session/side from that log, entirely offline (no Deriv connection
needed). A trade Deriv closed on its own between two runs can only be
priced exactly when it's the *only* one that closed in that gap (the
balance delta is unambiguous); if several closed at once, they're logged
honestly with `pnl: null` ("unattributed") rather than a guessed split --
excluded from every pnl-based average, never silently treated as a
break-even trade. **The Deriv account dashboard is still the ground
truth** for anything this log can't yet attribute precisely.

**Safety model is different from Alpaca/OANDA's**, because Deriv's
account model is: Alpaca/OANDA use one base URL with a paper/live flag
that can be forced in the workflow regardless of secrets; Deriv's API
token is already scoped to one specific account (demo or real) the
moment it's created, so there's no URL to force. Instead, `broker.py`'s
`connect()` picks the account whose `account_type` is `"demo"` and
refuses to proceed on a real account unless `CFD_ALLOW_LIVE_TRADING`
is explicitly true -- which both CFD workflows still hardcode to
`"false"` regardless of secrets, as defense-in-depth on top of that
check.

**Status: connection and order flow confirmed end-to-end against a live
demo account.** `scripts/cfd_cli.py test-order` (opens a minimal-size
real order and closes it right away -- diagnostic only, not part of the
automated strategy loop) round-tripped successfully: connect, buy,
portfolio read, and sell all confirmed against live responses. Getting
there took several rounds of fixing assumptions that didn't match the
real API (each found by reading actual error responses/payloads, never
guessed): `DERIV_APP_ID` needs a registered application, not the shared
`1089`; account selection needed `account_type` ("demo"/"real"), not the
commonly-documented `is_virtual` field; the proposal request and
portfolio response both use `underlying_symbol`, not `symbol`; and a
brand-new contract can't be sold until Deriv processes its first price
tick (`test-order` retries on that specific transient error).

**Order placement is now confirmed end-to-end against a real market
instrument**, not just a synthetic index: `cryBTCUSD` (Bitcoin, one of
Deriv's crypto Multipliers -- discovered via a new `list-symbols`
CLI/workflow command rather than guessed, see `broker.py`'s
`list_active_symbols()`) round-tripped connect/buy/portfolio-read/sell
successfully. Crypto trades 24/7 on Deriv, unlike forex/gold which
close on weekends -- useful for testing when `CFD_INSTRUMENTS`' own
markets are shut, as they were when this was run. Confirmed multiplier
values differ by instrument yet again: `cryBTCUSD` accepts
100/200/300/500/800, not `risk.py`'s default of 20.

**Update 2026-09-19: forex/gold instruments confirmed too.** Two full
scheduler runs (`scripts/run_cfd_trading.py`, via the `CFD Trading`
workflow's manual dispatch) against the real configured instruments
(`frxXAUUSD` etc.) completed cleanly -- candle fetches succeeded, no
"market closed" errors, no exceptions. The first run also confirmed the
virtual-equity baseline capture (`trading.cfd.capital`) and capital
floor set correctly against the live account; the second run's
set-once baseline logic correctly made no changes. The `cfd-trading.yml`
cron schedule is now enabled on that basis (previously commented out --
see git history for that earlier caution, from before this system had
the virtual equity model, Trade Database, or any of the safety layers
described above it in this section). Deriv's per-instrument `multiplier`
caps are still discovered empirically as each one is actually used
(same "confirm against a live response, never guess" discipline as
everywhere else in this file), not exhaustively pre-verified. (Crypto
isn't a drop-in fix for forex/gold's own validated parameters --
`EmaCrossoverStrategy`'s params were validated on forex/gold data only,
not crypto's different volatility profile, so `cryBTCUSD`/`cryETHUSD`
still need their own backtest before joining `CFD_INSTRUMENTS`, even
though their order mechanism works.)

**Backtesting: `scripts/optimize_cfd_strategy.py` (`CfdBacktestEngine`
in `src/trading/cfd/backtest.py`)** mirrors `optimize_strategy.py`'s
TRAIN/TEST discipline for `EmaCrossoverStrategy`, with two gates the
stock version doesn't need, both earned the hard way across several
real runs:
- The winning candidate has to beat the untouched default params' own
  TEST performance, not just clear CAGR>0 and the drawdown cap in
  isolation -- a candidate that passes that bar alone but does worse
  than doing nothing on real holdout data is not an improvement.
- Ranking by TRAIN calmar alone isn't enough either: the top `TOP_N_TO_TEST`
  TRAIN-qualified candidates all get evaluated on TEST, and the winner is
  whichever both clears the gate and beats baseline, ranked by *TEST*
  calmar -- the TRAIN-calmar #1 candidate turned out to be a
  catastrophic overfit (35% TRAIN CAGR, -46% TEST CAGR) that a naive
  "just test #1" selection would have missed.

**History depth turned out to be the real obstacle.** Deriv's
`ticks_history` only serves roughly the last **3 months** of `M15`
(15-minute) candles for these instruments, however far back `end` is
paged -- confirmed by running the identical pagination logic at `H1`
(hourly) granularity, which reached back ~11 months without issue (a
server-side limit, not a fetch bug). Even that wasn't enough: the
optimizer also supports `--source yfinance` (Yahoo Finance, already a
trusted dependency here for the stock system's earnings dates) as a
credible longer-history cross-check, reaching **~2-2.9 years** of
hourly data for EUR/USD, GBP/USD, USD/JPY, and gold (via `GC=F` COMEX
futures, since `XAUUSD=X` isn't a valid Yahoo ticker) -- a different
vendor/feed than Deriv, so treated as directional, not identical to
Deriv's own prices.

That longer window changed the conclusion entirely. The **original**
defaults (12/26 EMA spans, 1.5/2.5 ATR multiples, aimed at M15 bars)
scored a **-30.8% TRAIN CAGR and -65.5% max drawdown** over ~2 years of
H1 data -- 1143 trades at a 34% win rate, i.e. whipsaw in ranging
FX/gold, not something nearby fine-tuning fixes. A widened grid search
(wider EMA separation, wider stops) found only 2 of 81 combinations
held up out-of-sample at all; `EmaCrossoverStrategy`'s defaults are now
the better of those two (`fast_span=15, slow_span=34, atr_stop_mult=2.0,
atr_target_mult=2.0` -- TRAIN cagr=3.4% maxdd=-19.9%, TEST cagr=4.8%
maxdd=-13.9%, win_rate=47.6% both periods: modest but genuinely
consistent, unlike the overfit candidates). Because this was only
validated at H1, `scheduler.py`'s granularity moved from M15 to H1 to
match -- copying H1-validated EMA spans onto M15 bars would silently
change what they mean (15 H1 bars is 15 hours of lookback, not 15 x 15
minutes), so the live bot now trades what was actually tested rather
than an extrapolation across timeframes. Revisiting M15 (probably via
the live bot's own accumulated trade history, once there's enough of
it) stays a reasonable future step, not a requirement -- H1 is a fully
valid, deliberately-chosen granularity now, not a placeholder.

**Risk-per-trade sweep (`scripts/sweep_cfd_risk.py`).** After validating
the strategy above, there was a request to reach a much faster
capital-doubling timeline than the validated ~3-5%/year CAGR implies
(months rather than the ~15-21 years that CAGR works out to). Rather
than guess a bigger `CFD_RISK_PER_TRADE`, this script holds
`EmaCrossoverStrategy` fixed at its validated defaults and backtests a
grid of `risk_per_trade` values (1% to 50%) on both TRAIN and TEST,
alongside a blunt "equity left after N consecutive full-stop losses in
a row" figure for each.

**Result: raising risk_per_trade doesn't trade a bit more risk for a
lot more return here -- it makes the return worse too**, not just the
drawdown. CAGR fell from -2.3% (TRAIN, 1% risk) to -84.0% (TRAIN, 50%
risk) essentially monotonically, with max drawdown sliding from -24.9%
to -99.0% over the same range -- a Kelly-criterion / volatility-drag
effect: this strategy's edge (win rate ~46-48%, Sharpe mostly under 1)
is too thin to support leveraging past a small risk fraction; sizing
bets larger than the edge supports actively destroys long-run growth,
it doesn't just add variance around a bigger number. A run of 10
ordinary losses (unremarkable for a ~47% win-rate strategy) leaves as
little as 35% of equity at 10% risk/trade, and under 1% at 30%+.

Also notable: re-running the baseline (1% risk, same validated params)
against a slightly later data window than the original validation shows
TRAIN CAGR slipping to -2.3% (from the original +3.4%) -- the edge is
real but not large or perfectly stable across time, another reason not
to lean on it harder rather than less. **Conclusion: no risk_per_trade
value gets this strategy to a months-scale doubling goal without a high
probability of ruin; `CFD_RISK_PER_TRADE` stays at its conservative
default (0.01) rather than being raised.** A faster timeline, if wanted
later, needs a higher-edge strategy (or an entirely different approach),
not a bigger bet size on this one.

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
  cfd/                        # separate CFD/forex (Deriv) system -- see "CFD/forex trading" above
    broker.py                   # Deriv WebSocket API calls -- confirmed live against a real demo account
    strategy.py                   # intraday EMA crossover, long or short (validated)
    breakout.py                    # Donchian channel breakout, long or short (unvalidated as of writing)
    capital.py                      # virtual equity model -- rebases demo P&L onto $100, see "Capital model" above
    risk.py                          # stake/multiplier sizing, capital floor, daily-loss circuit breaker, min-stake SKIP TRADE guard
    strategy_registry.py              # Strategy Registry -- name@version, lifecycle states, promotion audit trail
    regime.py                          # Market Regime Engine -- per-instrument trending/ranging/unknown via ADX
    selector.py                         # Strategy Selector -- matches regime against ACTIVE strategies' suited_regimes
    failure_analysis.py                  # Failure Analysis -- loss classification + strategy degradation detection
    validation.py                         # Walk-Forward + Monte Carlo / Stress Test
    research_lab.py                        # Research Lab -- candidate generation/evaluation, auto-registers passing ones as VALIDATED
    operating_mode.py                       # Defensive/Normal/Aggressive/Recovery risk-sizing multipliers, hard-capped
    paper_trading.py                         # Paper Trading -- runs PAPER-state strategies on live candles, no real orders
    manager_report.py                         # AI Trading Manager report -- consolidated view + recommended commands, never auto-applied
    trade_log.py                       # Trade Database -- append-only JSONL log of closed trades
    performance.py                      # Performance Engine -- metrics computed from the trade log
    scheduler.py                         # one strategy evaluation + order pass, every ~1h (async)
    state.py                              # paused flag, capital floor, broker baseline, open-trade tracking, excluded instruments
    backtest.py                            # CfdBacktestEngine -- TRAIN/TEST discipline, mirrors backtest/engine.py
scripts/
  run_backtest.py
  compare_strategies.py       # all strategies x several market regimes
  optimize_strategy.py         # train/test parameter grid search (calmar or win_rate)
  run_paper_trading.py          # used by the daily-trading.yml workflow
  cli.py                         # status / pause / resume / buy / sell / set-floor / cancel -- used by manual-command.yml
  run_cfd_trading.py               # used by cfd-trading.yml
  cfd_cli.py                         # status / pause / resume / exclude-instrument -- used by cfd-manual-command.yml
.github/workflows/
  daily-trading.yml
  manual-command.yml
  backtest.yml
  compare-strategies.yml
  optimize-strategy.yml
  cfd-trading.yml
  cfd-manual-command.yml
state/
  bot_state.json
  positions.json
  buckets.json
  cfd_bot_state.json
  cfd_trades.jsonl        # Trade Database -- see "Trade Database & Performance Engine" above
  cfd_paper_trades.jsonl   # Paper Trading log -- separate from the real Trade Database, see "Paper Trading" above
  cfd_strategy_registry.json  # Strategy Registry -- see "Strategy Registry & lifecycle" above
docs/
  VISION.md                # master vision for the AI Trading Manager -- read this first
  ARCHITECTURE_AUDIT.md      # what exists vs. the vision, and what's still missing
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

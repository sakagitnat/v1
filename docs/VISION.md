# AI Trading Manager — Master Vision

Status: **approved master vision**, recorded 2026-09-19. This document is the
source of truth for what the Deriv trading system is supposed to become. Any
future design decision that conflicts with this file should either update
this file (with explicit user sign-off) or be rejected.

## What this is not

Not a single-strategy bot. The system being built is an **AI that manages a
portfolio of trading strategies** the way a discretionary trading desk
manager would: deciding what to trade, when *not* to trade, which edge to
use, how much risk to take, and when a strategy has stopped working.

## What the AI Trading Manager must do

- Analyze the market and understand the current **market regime**
- Choose BUY / SELL / NO TRADE
- Select the strategy best suited to the current regime
- Adjust strategy parameters within a pre-approved safe range
- Analyze its own trading results
- Diagnose *why* a loss happened
- Detect strategy degradation
- Generate new strategy candidates
- Test new strategies before they ever trade real/demo money
- Pause or retire strategies that stop working
- Allocate risk according to market conditions
- Keep improving as more data accumulates

## Ultimate objective

Maximize **long-term compounded equity growth** under hard risk constraints.
Not "profit every day" or "profit every month." The $100 → ~$200/month goal
is a **stretch research objective only** — never a justification for
dangerous risk-taking.

## Target pipeline

```
Deriv Market Data
  -> Market Regime Engine
  -> AI Trading Manager
  -> Strategy Selector
  -> BUY / SELL / NO TRADE
  -> Risk Governor              (AI may not override this layer)
  -> Execution Engine
  -> Deriv
  -> Trade Database
  -> Performance Engine
  -> Failure Analysis
  -> Research / Improvement Lab
  -> Validation
  -> Strategy Registry
  -> back into AI Trading Manager
```

**Risk Governor sits above the AI. The AI is never allowed to override it.**

## Hard prohibitions

- No martingale
- No revenge trading
- No increasing risk because of a loss
- No increasing risk because profit target hasn't been hit yet
- No hot-editing a live strategy without going through validation first
- No use of future data / lookahead leakage
- No promoting a strategy because backtest looked good over one lucky window
- **No deliberately trading an account's balance down or up to hit a target
  number.** (This directly forbids anything like the existing
  `scripts/burn_demo_balance.py` — see the architecture audit.)

## Strategy pool (target, not all built yet)

Trend Following, Breakout, Momentum, Mean Reversion, Volatility Expansion,
Pullback, Multi-Timeframe, and NO TRADE as a first-class strategy (not just
an absence of signal).

The AI should learn **which strategy fits which regime** — not search for
one strategy that works in every market.

## Strategy lifecycle

Every strategy has a version and moves through:

```
RESEARCH -> CANDIDATE -> VALIDATED -> PAPER -> ACTIVE -> PAUSED -> RETIRED
```

New candidates must pass, in order:

```
Backtest -> Validation -> Out-of-Sample -> Walk-Forward
  -> Monte Carlo / Stress Test -> Paper Trading -> Promote or Reject
```

## Performance Engine — minimum tracked metrics

net return, expectancy, profit factor, win rate, average win / average
loss, R multiple, Sharpe, Sortino, Calmar, max drawdown, longest losing
streak, performance by strategy, performance by regime, performance by
session, long vs short, exposure, trade count.

## Failure Analysis — loss classification

normal statistical loss, wrong market regime, bad entry, strategy
mismatch, strategy degradation, spread/slippage problem, execution
problem, data problem, abnormal market/news event, excessive risk.

## Operating modes

Defensive, Normal, Aggressive, Recovery, Paused — **all of them still bound
by the same hard risk limits.** A mode changes tactics, never the ceiling.

## Capital model — critical, do not violate

Deriv's demo account shows a broker balance of roughly **$10,000** (Deriv's
fixed demo default). The user's real intended starting capital is **$100**.

- `BROKER_DEMO_BALANCE` ≈ $10,000 (Deriv's fixed demo default, recorded once
  as a baseline at first run)
- `VIRTUAL_STARTING_CAPITAL` = $100 (what all sizing/risk/performance logic
  must actually use)

Formula: `virtual_equity = VIRTUAL_STARTING_CAPITAL + (broker_balance -
BROKER_DEMO_BALANCE_baseline)`.

Example: baseline broker balance $10,000, virtual start $100. Broker balance
$10,010 -> virtual equity $110. Broker balance $9,980 -> virtual equity $80.

Risk sizing, drawdown tracking, performance metrics, and capital management
on demo must **all** be computed from virtual equity, never from the raw
broker balance.

It is forbidden to deliberately trade the demo account's $10,000 down to
$100 (or any other target) to make the numbers look right — see hard
prohibitions above. If Deriv's own minimum order/stake size makes it
impossible to keep a $100-scale account within the configured risk limit,
the correct behavior is **SKIP TRADE** — never round the position size up
past the configured risk.

## Broker / product notes

Deriv **native API** (the `/trading/v1/options` REST+OTP+WebSocket flow),
trading **Multipliers** (`MULTUP` / `MULTDOWN`) — not traditional MT5 CFDs,
not classic binary options. See `src/trading/cfd/broker.py`'s docstring for
the confirmed connection flow and gotchas.

## Long-run design loop

```
Observe -> Understand Market -> Select Edge -> Size Risk -> Execute
  -> Measure -> Diagnose -> Research -> Validate -> Adapt -> Repeat
```

The AI does not need to be right 100% of the time. It needs to: be wrong
less often, lose less when wrong, exploit real edge well when it has one,
know when *not* to trade, detect strategy decay early, and adapt faster
than the market's edge disappears.

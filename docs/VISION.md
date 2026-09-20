# AI Trading Manager — Master Vision

Status: **approved master vision**, recorded 2026-09-19, **revised
2026-09-20** after the user clarified that an earlier implementation pass
had interpreted this narrower than intended (see "Revision history" at the
end). This document is the source of truth for what the Deriv trading
system is supposed to become. Any future design decision that conflicts
with this file should either update this file (with explicit user sign-off)
or be rejected. **Before any large code change, check whether it actually
moves the system toward this architecture — not just whether it's a
reasonable improvement in isolation.**

## What this is not

Not a single-strategy bot, and not "one strategy runs until it stops
working, then gets swapped for the next one." The system being built is an
**AI that manages a portfolio of trading strategies** the way a
discretionary trading desk manager would: deciding what to trade, when
*not* to trade, which edge(s) to use — possibly several at once, weighted
by conviction and regime fit — how much risk to take, and when a strategy
has stopped working. A single validated strategy (e.g. the EMA crossover
described below) is one input to this system, not a description of its
ceiling. Its current, thin backtest numbers are not a benchmark the
architecture should be judged against — they're one early candidate's
result, not a limit on what the system is ultimately capable of finding.

## What the AI Trading Manager must do

- Analyze the market and understand the current **market regime** — richer
  than trend direction alone: trending vs. ranging, high vs. low
  volatility, and an explicit "unstable / don't trade" condition, not just
  an absence of signal
- Choose BUY / SELL / NO TRADE
- Select **one or more** strategies suited to the current regime, and
  decide how to **allocate** capital/risk across them if more than one is
  in play — not necessarily winner-take-all
- Adjust strategy parameters and allocation weights within a pre-approved
  safe range
- Analyze its own trading results, per strategy, not just portfolio-level
  P&L
- Diagnose *why* a loss happened
- Detect strategy degradation continuously, not on request
- **Demote, reduce the allocation of, or pause a decaying strategy on its
  own, within the autonomy boundaries below** — without waiting for a
  human to approve each instance
- Generate new strategy candidates
- Test new strategies before they ever trade real/demo money
- Retire strategies that stop working, and send decaying ones back through
  the Research Lab rather than just stopping them
- Allocate risk according to market conditions
- Keep improving as more data accumulates

## Autonomy boundaries — what the AI may decide on its own vs. what needs a human

This is the part the first implementation pass got too conservative about:
not every safety-relevant action needs a human to click approve. The
boundary is about **direction**, not about which subsystem is involved.

**The AI may act on its own** (still logged, still fully within the hard
limits below, but no per-instance human approval required):
- Choosing BUY / SELL / NO TRADE each run
- Selecting which ACTIVE strategy or strategies trade a given regime, and
  how allocation is split between them
- Reducing a strategy's allocation, demoting it (e.g. ACTIVE -> PAUSED), or
  sending a decaying strategy back into the Research Lab pipeline for
  re-validation
- Cutting exposure or going flat when conditions warrant it
- Anything that only ever moves risk **down**, never up, and never crosses
  a hard limit

**A human must explicitly approve:**
- Raising any hard risk ceiling (`CFD_MAX_RISK_PER_TRADE_CEILING`, max
  drawdown limits, max exposure, capital floor changes that loosen
  protection)
- Enabling real-money trading (`CFD_ALLOW_LIVE_TRADING`) or increasing real
  capital committed
- Changing the safety architecture itself (this file, the Risk Governor's
  code, the lifecycle rules)
- Promoting a strategy that has not passed the required validation stages
  (see "Strategy lifecycle" below) — most importantly, **PAPER -> ACTIVE**
  always needs a human, because that's the step that first risks real (or
  virtual-real) capital on a strategy's live behavior rather than its
  backtest

The dividing line: the AI can freely make the system *more conservative*
on its own initiative; it can never make the system *more aggressive* or
cross a safety boundary without a human saying so explicitly. A user who
has approved this framework does not need to re-approve every individual
strategy swap or allocation cut that stays inside it.

## Ultimate objective

Maximize **long-term compounded equity growth** under hard risk constraints,
by continuously finding, preserving, and (re)allocating real edge as market
conditions change. Not "profit every day" or "profit every month," and not
"whatever the first validated strategy's backtest happened to show." The
$100 → ~$200/month goal is a **stretch research objective only** — a way to
see how much capital growth a genuinely strong edge could produce under
still-reasonable risk constraints, never a justification for
dangerous risk-taking or a ceiling implied by any one strategy's current
numbers.

## Target pipeline

Two tracks, running in parallel:

```
Market Data
  -> Market Regime Detection      (trending/ranging x high/low-vol x unstable)
  -> Strategy Pool                (multiple validated strategies, not one)
  -> AI Trading Manager           (BUY/SELL/NO TRADE, strategy fit)
  -> Portfolio / Allocation Decision   (single strategy OR a weighted mix)
  -> Hard Risk Governor           (AI may not override this layer)
  -> Execution Engine
  -> Deriv
```

```
                                    (parallel, continuous)
Trade Database
  -> Performance Engine            (per strategy, per regime, not just portfolio total)
  -> Live Performance Monitor
  -> Strategy Decay Detection
  -> Demote / Pause                (AI-autonomous, within the boundaries above)
  -> Research Lab
  -> Candidate Generation
  -> Backtest / Train-Test / Walk-Forward / Monte Carlo / Paper / Shadow
  -> Promote Strategy              (human-approved: PAPER -> ACTIVE)
  -> back into Strategy Pool
```

**Risk Governor sits above the AI, on the execution path. The AI is never
allowed to override it, on either track.**

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
- No AI-initiated action that raises a hard risk ceiling, enables real
  money, or promotes a strategy past PAPER -- see "Autonomy boundaries"
  above; these always need a human.

## Strategy pool (target, not all built yet)

Trend Following, Breakout, Momentum, Mean Reversion, Volatility Expansion,
Pullback, Multi-Timeframe, and NO TRADE as a first-class strategy (not just
an absence of signal). As of the last architecture audit, the pool has
exactly two trend-following members (EMA crossover, Donchian breakout) and
nothing for ranging/mean-reverting conditions — a real, tracked gap, not
something to treat as "good enough."

The AI should learn **which strategy fits which regime**, and be able to
run more than one at once when more than one fits — not search for one
strategy that works in every market, and not assume only one may ever be
"in charge."

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

Forward promotion always needs a human at the PAPER -> ACTIVE step (see
"Autonomy boundaries"). Backward movement (ACTIVE -> PAUSED, PAUSED ->
RETIRED, or ACTIVE -> back into the Research Lab for re-validation) is
something the AI may initiate on its own when Failure Analysis detects
decay, logged and explained, not silently applied.

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
broker balance. This is a virtual equity *ledger* the AI manager reasons
about — sizing, drawdown, and compounding all read from it — never from
the raw broker balance, and never by touching the real balance to make the
numbers line up.

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
Observe -> Understand Market -> Select Edge(s) -> Allocate -> Size Risk
  -> Execute -> Measure -> Diagnose -> Decay-Check -> Research -> Validate
  -> Adapt -> Repeat
```

The AI does not need to be right 100% of the time. It needs to: be wrong
less often, lose less when wrong, exploit real edge well when it has one
(or several, weighted by how well each fits current conditions), know
when *not* to trade, detect strategy decay early and act on it within its
own authority, and adapt faster than the market's edge disappears — all
without ever needing a human to sign off on making the system safer.

## Revision history

- **2026-09-19**: initial recording of the master vision, from the
  project's original brief.
- **2026-09-20**: user flagged that the first implementation pass (the
  Strategy Registry / Selector / Failure Analysis / Research Lab / Paper
  Trading built across that day) had interpreted this too narrowly — as a
  single-winner strategy selector with every lifecycle change, including
  routine demotions, requiring manual human approval. This revision adds:
  explicit multi-strategy Portfolio/Allocation as a pipeline stage; an
  "Autonomy boundaries" section distinguishing what the AI may decide
  unilaterally (anything that only reduces risk/exposure) from what always
  needs a human (raising risk ceilings, going live, increasing real
  capital, changing safety architecture, promoting past PAPER); a richer
  target regime taxonomy (volatility dimension, explicit "unstable"
  condition); and an explicit statement that the current EMA crossover
  strategy's backtest numbers are one early candidate's result, not a
  ceiling on the architecture.

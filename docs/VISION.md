# AI Trading Manager — Master Vision

Status: **approved master vision**, recorded 2026-09-19, revised 2026-09-20
(multi-strategy portfolio + autonomy boundaries), **revised again 2026-09-20
("Revision 3")** after the user and GPT independently converged on a fuller
picture and the user asked for it recorded as the explicit source of truth
before further development (see "Revision history" at the end). This
document is the source of truth for what the Deriv trading system is
supposed to become. Any future design decision that conflicts with this
file should either update this file (with explicit user sign-off) or be
rejected. **Before any large code change, check whether it actually moves
the system toward this architecture — not just whether it's a reasonable
improvement in isolation.** After Revision 3, the system must never again be
interpreted back down into a single-strategy bot, a fixed-holding-period
bot, or a "lowest possible risk" bot — see "What this is not" below.

## What this is not

- Not a single-strategy bot, and not "one strategy runs until it stops
  working, then gets swapped for the next one."
- Not "the safest bot possible." Minimizing risk to near-zero is not the
  goal — finding and sizing genuine edge, under hard limits that are
  real but not so tight they prevent the system from ever taking a
  meaningful position, is.
- Not a bot that opens at most one position at a time, or that must wait
  for one trade to close before considering another. Multiple independent
  positions, across multiple instruments and multiple strategies, can be
  open simultaneously.
- Not a bot with a fixed holding period. A trade lasting minutes and a
  trade lasting several days are both normal outcomes of the same system,
  decided by whether the edge that justified the trade is still present —
  never by a clock.
- Not a bot that caps every winner at a fixed R-multiple take-profit.
  Initial risk and realized upside are different decisions; a small,
  disciplined loss can sit next to a rare, large, multi-R winner from the
  same strategy.
- Not a bot with a fixed daily trade-count target. Some days may produce
  zero trades, some may produce fifteen — driven entirely by how many
  genuine, independent, quality opportunities actually appear, never by a
  quota in either direction.

The system being built is an **AI that manages a portfolio of trading
strategies, markets, and open positions at once** the way a discretionary
trading desk manager would: deciding what to trade, when *not* to trade,
which edge(s) to use — possibly several at once, weighted by conviction and
regime fit — how many positions to hold concurrently, how much risk each
one gets, how long to hold each one, when to protect a winner or cut a
loser, and when a strategy has stopped working. A single validated strategy
(e.g. the EMA crossover described below) is one input to this system, not a
description of its ceiling. Its current, thin backtest numbers are not a
benchmark the architecture should be judged against.

## What the AI Trading Manager must do

- Analyze the market and understand the current **market regime** — richer
  than trend direction alone: trending vs. ranging, high vs. low
  volatility, and an explicit "unstable / don't trade" condition, not just
  an absence of signal
- Find and evaluate **opportunities across multiple markets and multiple
  strategies concurrently**, not just re-evaluate one instrument/strategy
  pair per cycle
- Choose BUY / SELL / NO TRADE **independently per opportunity** — several
  independent BUY/SELL decisions can be live at once, each sized and
  managed on its own
- Select **one or more** strategies suited to the current regime, and
  decide how to **allocate** capital/risk across them if more than one is
  in play — not necessarily winner-take-all
- Decide, per position, how many to hold concurrently, how long to hold
  each one, whether to trail a stop, take partial profit, or let a winner
  run — never a single fixed rule applied uniformly to every trade
- Adjust strategy parameters and allocation weights within a pre-approved
  safe range
- Analyze its own trading results, per strategy, per regime, and at the
  **portfolio level** (correlation and concentration across simultaneously
  open positions, not just each position judged alone)
- Diagnose *why* a loss happened
- Detect strategy degradation continuously, not on request
- **Demote, reduce the allocation of, or pause a decaying strategy on its
  own, within the autonomy boundaries below** — without waiting for a
  human to approve each instance
- Generate new strategy candidates
- Test new strategies before they ever trade real/demo money, in a
  Research environment kept strictly separate from Qualification (see
  below)
- Retire strategies that stop working, and send decaying ones back through
  the Research Lab rather than just stopping them
- Allocate risk according to market conditions, drawdown state, and
  portfolio-level exposure — not just per-trade in isolation
- Keep improving as more data accumulates

## Risk model — per-position, per-thesis, correlated, and portfolio ceilings

This is the part most likely to be misread if skimmed, so it's spelled out
in full.

**What "risk 1%" means.** A stated risk of 1% is the *estimated maximum
loss of one position if its stop is hit* — not the dollar amount put into
the order, and not a number that ignores execution reality: sizing should
leave headroom for slippage/spread around the stop, not assume a perfect
fill exactly at the stop price.

**Multiple concurrent positions are normal, not an exception.** The system
is not limited to one trade at a time. On a $100 account, five independent
opportunities (A through E) each risking about $1 can all be open at once —
that's roughly 5% of the portfolio at risk simultaneously, and it's fine
*if* all five are genuinely independent opportunities.

**Splitting one thesis into many orders to dodge the per-position limit is
forbidden.** Five long orders on XAUUSD at 1% each is not five
opportunities if they all came from the same underlying thesis (e.g. "gold
breaks out here") — that's one thesis, and it must be tracked and capped as
**one risk bucket**, not five separate 1% allowances stacked into a
disguised 5%.

**Correlation must be accounted for, not just instrument name.** Several
positions that are really the same bet in different clothing (e.g. several
"USD weakens" trades across different pairs) must have their risk summed
and judged together, never treated as diversified just because the
instrument tickers differ.

**Required risk ceilings, all enforced by the Hard Risk Governor, none of
them optional:**
- per-position risk ceiling (exists today: `risk_per_trade`,
  `CFD_MAX_RISK_PER_TRADE_CEILING`)
- total portfolio risk ceiling — the sum of every currently-open position's
  risk, capped explicitly (not just implied by a position-count limit)
- correlated-risk ceiling — the sum of risk across positions sharing a
  common factor, capped separately from the raw portfolio total
- per-thesis risk ceiling — one underlying idea, however many
  instruments/orders it's expressed through, capped as one bucket
- total exposure/leverage ceiling — an aggregate cap on notional exposure,
  not just per-trade multiplier

**No fixed daily trade-count.** Zero trades one day and fifteen the next
are both fine, driven by how many quality opportunities actually exist.
The AI must never lower its entry quality bar to manufacture trades toward
a target, and must never raise trade frequency to chase back a loss —
either one is a disguised form of the martingale/revenge-trading pattern
already forbidden below.

**Growth comes from multiplication, not from bigger bets:**

```
growth ≈ (quality opportunities found)
        × (positive expectancy per opportunity)
        × (genuine diversification across strategies/markets)
        × (asymmetric payoff — winners that run, losses that stay small)
        × (adaptive holding period)
        × (compounding)
```

not from raising risk-per-trade to gambling-sized bets.

## Position holding period and exit philosophy

- **No fixed holding period.** The AI decides per trade whether the edge
  justifies minutes, hours, a full day, or several days — never a uniform
  rule applied to every strategy or every trade.
- **Initial risk and realized upside are separate decisions.** A $1 initial
  risk does not imply a $1–2 profit cap. The same trade might close at
  -$1, +$2, +$5, +$20, or +$50 depending on how far the move actually
  goes — 1% risk describes the downside being budgeted, not a ceiling on
  the upside being sought.
- **Cut losers, let winners run — but never without a reason.** Exit when
  the thesis breaks or the regime changes; stay in while the edge is still
  present. A profitable position may use a trailing stop, an
  adaptive/regime-aware exit, or a partial close — staying in is not the
  same as staying in blindly.
- **No fixed take-profit applied uniformly across a strategy** (e.g. "close
  every trade at exactly 2R, no exceptions"). A rigid full-position
  take-profit at a small fixed multiple can quietly kill the rare large
  winners that a positive-expectancy system's overall edge often depends
  on. At the same time, a large unrealized gain must never be allowed to
  round-trip back to a loss with no protective logic at all — profit
  protection (trailing stop, adaptive exit, or partial close) is required
  once a position is meaningfully in profit, it just isn't a single fixed
  number applied identically everywhere.
- **Partial close must be supported**, e.g. closing part of a position at
  +5R and letting the remainder run, to balance realized profit against
  tail upside rather than forcing an all-or-nothing exit decision on every
  winning trade.

## Growth objective and what it does not license

The research objective is for roughly $100 to have a real chance of growing
toward roughly $200 over about a month, driven by genuine edge, trade
frequency, and compounding. **This is not a "+100% every month" mandate.**
If a given month doesn't produce enough genuine opportunity, the system
must accept slower growth or no growth that month, never manufacture
activity to chase the number. The following are explicitly forbidden as
ways to chase the growth objective, on top of the hard prohibitions
already listed below:
- martingale
- revenge trading
- increasing risk after a loss
- increasing leverage without evidence supporting it
- overtrading (lowering the entry quality bar to hit a trade-count target)
- lowering the quality/validation threshold for a strategy or a signal

The target is not "one trade makes the month." It's the system
accumulating edge across many trades, while staying genuinely open to the
rare large winner (many R, not capped) that a good positive-expectancy
system will occasionally produce.

## Allocation, conviction, and the risk ladder

The AI may raise or lower a strategy's allocation based on confidence and
evidence — never on a winning streak alone. Before increasing allocation to
a strategy, the evidence must include: sample size, live (not just
backtest) expectancy, regime fit, current drawdown, correlation with
everything else currently allocated, live-vs-backtest deviation, and any
sign of decay.

Any risk increase — for a single strategy's allocation or for the
account's overall risk-per-trade — must move through a **qualified risk
ladder** (e.g. 1% → 2% → 3% → 5%), each rung requiring its own evidence
before the next is used. The AI may move a strategy or the account **down**
this ladder on its own initiative (see "Autonomy boundaries"). Moving
**up** a rung, and the ladder's own top rung (the hard ceiling), both still
require a human — the AI can never climb the ladder past what evidence has
already qualified, and never past the hard ceiling regardless of evidence.

## Drawdown handling

The system needs a drawdown mode, not a single fixed risk level held
stubbornly through any size of losing stretch. Illustrative tiers (exact
numbers are a config decision, not fixed by this document):

```
normal              -> full configured risk_per_trade
moderate drawdown    -> reduced (e.g. 0.75x)
deeper drawdown       -> further reduced (e.g. 0.5x)
serious abnormality    -> halt new entries entirely
```

The system must distinguish a **random losing streak** (statistically
normal for a positive-expectancy strategy) from **genuine strategy decay**
(the edge itself has degraded) — they call for different responses: a
losing streak calls for the drawdown tiers above (temporary, recovers when
losses do), decay calls for demotion (see "Strategy lifecycle").

Recent profit is not a license to scale risk back up immediately and in
full. Equity moving from $100 to $120 doesn't mean every risk calculation
should instantly re-baseline off $120 — a smoothed equity figure, a
confirmed-growth check, or high-water-mark-based logic should temper how
fast risk scales up with a recent gain, to avoid oscillating risk up and
down with short-term noise.

## Portfolio-level risk analysis

The system must be judged and gated at the **portfolio** level, not only
strategy-by-strategy. Two strategies that each look fine in isolation can
be dangerous run together if they're correlated — so the system must
track, at minimum: portfolio-level expectancy and drawdown, concentration
(how much risk sits in one thesis/instrument/correlated group),
common-factor exposure across simultaneously open positions, and overlap
between strategies currently allocated risk.

**Portfolio-level NO TRADE must exist as its own gate.** Even when several
strategies independently want to enter, the Hard Risk Governor must be able
to refuse a new entry purely because the *portfolio's* total risk,
correlated exposure, or concentration is already at its ceiling — a
rejection the per-position risk check alone would never catch.

## Autonomy boundaries — what the AI may decide on its own vs. what needs a human

Not every safety-relevant action needs a human to click approve. The
boundary is about **direction**, not about which subsystem is involved.

**The AI may act on its own** (still logged, still fully within the hard
limits below, but no per-instance human approval required):
- Choosing BUY / SELL / NO TRADE per opportunity, independently across
  multiple markets and strategies at once
- Selecting which ACTIVE strategy or strategies trade a given regime, and
  how allocation is split between them
- How many positions to hold concurrently, up to the hard ceilings
- Per-trade holding period, trailing stop use, partial-close decisions, and
  regime-aware exit timing
- Reducing a strategy's allocation, demoting it (e.g. ACTIVE -> PAUSED), or
  sending a decaying strategy back into the Research Lab pipeline for
  re-validation
- Moving down the risk ladder, cutting exposure, or going flat when
  conditions warrant it
- Anything that only ever moves risk **down**, never up, and never crosses
  a hard limit

**A human must explicitly approve:**
- Raising any hard risk ceiling: max risk per position
  (`CFD_MAX_RISK_PER_TRADE_CEILING`), max portfolio risk, max correlated
  risk, max per-thesis risk, max exposure/leverage, max drawdown limits, or
  any capital-floor change that loosens protection
- Moving **up** the risk ladder to a rung not yet qualified by evidence
- Enabling real-money trading (`CFD_ALLOW_LIVE_TRADING`) or increasing real
  capital committed
- Changing the safety architecture itself (this file, the Risk Governor's
  code, the lifecycle rules, the kill switch)
- Promoting a strategy that has not passed the required validation stages
  (see "Strategy lifecycle") — most importantly, **PAPER -> ACTIVE** always
  needs a human

The dividing line: the AI can freely make the system *more conservative* on
its own initiative — including in ways specific to this revision, like
choosing to hold fewer, smaller, or shorter-lived positions — and it can
freely make case-by-case tactical decisions (which strategy, which
instrument, how long to hold, whether to trail or partial-close) as long as
those decisions stay inside limits a human already approved. It can never
make the system *more aggressive in aggregate* or cross a safety boundary
without a human saying so explicitly.

## Ultimate objective

Maximize **long-term compounded equity growth** under hard risk constraints,
by continuously finding, preserving, and (re)allocating real edge — across
multiple strategies and multiple markets, with position count, sizing, and
holding period all chosen by the system per opportunity — as market
conditions change. Not "profit every day" or "profit every month," and not
"whatever the first validated strategy's backtest happened to show." The
$100 → ~$200/month goal is a **stretch research objective only** — never a
justification for dangerous risk-taking, artificial trade frequency, or a
ceiling implied by any one strategy's current numbers.

## Target pipeline

```
Market Data
  -> Regime Detection            (trending/ranging x high/low-vol x unstable)
  -> Opportunity Detection       (multiple markets, multiple strategies, concurrently)
  -> Strategy Pool                (multiple validated strategies, not one)
  -> AI Trading Manager           (BUY/SELL/NO TRADE per opportunity, holding-period/exit choice)
  -> Portfolio Allocation         (position count, sizing, thesis/correlation-aware)
  -> Hard Risk Governor           (per-position, per-thesis, correlated, portfolio, leverage ceilings -- AI may not override)
  -> Execution Engine
  -> Deriv
```

```
                                    (parallel, continuous)
Trade Database
  -> Performance / Decay Monitoring   (per strategy, per regime, per portfolio)
  -> Demote / Pause                (AI-autonomous, within the boundaries above)
  -> Research & Validation         (see "Research vs. Qualification environments")
  -> Promote Strategy              (human-approved: PAPER -> ACTIVE)
  -> back into Strategy Pool
```

**Risk Governor sits above the AI, on the execution path. The AI is never
allowed to override it, on either track.**

## Research vs. Qualification environments — kept strictly separate

**Research environment**: free to experiment. Strategy logic can be
changed, parameters swept, stress tests run, high-risk scenarios tried, and
a simulated portfolio is *allowed* to break — the point is finding failure
modes on purpose, in a space where breaking things costs nothing and
teaches something.

**Qualification environment**: the opposite discipline. A strategy version
is **frozen** before qualification begins — no seeing a bad result midway
through and quietly adjusting a parameter to fix it; that's the definition
of overfitting to the qualification run itself. The exact frozen version
must clear, in order: unseen (out-of-sample) data, walk-forward validation,
Monte Carlo / shuffled-sequence stress testing, multiple market regimes,
stress conditions, live demo trading, and shadow mode — before it is even
a candidate for promotion.

"The system improves itself" never means "lost once, so adjust the
parameter immediately." Every strategy or parameter change follows the
full lifecycle:

```
Research -> Candidate -> Backtest -> Out-of-Sample -> Walk-Forward
  -> Simulation/Demo -> Shadow -> Qualification -> Promotion
```

## Strategy lifecycle

Every strategy has a version and moves through:

```
RESEARCH -> CANDIDATE -> VALIDATED -> PAPER -> ACTIVE -> PAUSED -> RETIRED
```

Forward promotion always needs a human at the PAPER -> ACTIVE step (see
"Autonomy boundaries"). Backward movement (ACTIVE -> PAUSED, PAUSED ->
RETIRED, or ACTIVE -> back into the Research Lab for re-validation) is
something the AI may initiate on its own when Failure Analysis detects
decay — the **Strategy Decay Monitor** — logged and explained, not silently
applied, and never requiring a human to press pause first.

## What the AI Trading Manager chooses vs. what it may never touch

**The AI decides:**
- which strategy, which instrument, which side (long/short)
- how much allocation/risk for a given opportunity
- how many positions to hold concurrently
- how long to hold each one
- whether to take a partial exit, trail a stop, or let a position run
- or NO TRADE

**The AI may never change:**
- max portfolio risk
- max leverage / exposure
- max correlated risk
- capital protection rules (capital floor, drawdown halt)
- the kill switch
- real-money trading permission
- the hard drawdown limit

The Hard Risk Governor always has authority over the AI, never the reverse.

## Execution realism and integrity

- **Backtests must model real costs**, not just idealized price movement:
  spread, slippage, commission, overnight/financing charges, rollover,
  price gaps, and market-hours limitations — especially for any trade held
  hours or days, where financing/rollover is no longer negligible.
- **Idempotency and reconciliation are required.** A GitHub Actions retry,
  reconnect, or crash-and-resume must never result in a duplicate order.
  The system must always be able to answer: which open position is this
  bot's, when did it open, which strategy/thesis/risk-bucket opened it, and
  which orders are already closed.
- **Manual or foreign trades must never silently blend into the system's
  own virtual equity or performance figures.** If a position exists in the
  broker account that this system didn't open, it must not be silently
  absorbed into the bot's own P&L/attribution without the system (or a
  human) explicitly recognizing it as external.

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
broker balance. It is forbidden to deliberately trade the demo account's
$10,000 down to $100 (or any other target) to make the numbers look right —
see hard prohibitions below. If Deriv's own minimum order/stake size makes
it impossible to keep a $100-scale account within the configured risk
limit, the correct behavior is **SKIP TRADE** — never round the position
size up past the configured risk.

## Qualification Gate before real money

The system must never simply *assert* it's ready for real money. Before
`CFD_ALLOW_LIVE_TRADING` is ever turned on, a Qualification Gate must show,
measurably:
- positive expectancy net of realistic costs
- passed unseen (out-of-sample) data
- passed multiple market regimes
- drawdown stayed within the configured envelope
- risk controls (per-position, per-thesis, correlated, portfolio,
  leverage, drawdown tiers) actually fired correctly when tested, not just
  exist in code
- no duplicate-execution incidents
- live/demo behavior did not diverge materially from the model that
  qualified it
- the strategy version was not modified during qualification
- no safety-rule violations occurred during the qualification run

Only after that does the system report **"qualified for risk level X"** —
and the human, not the AI, decides whether to actually enable real money.
This is an addition to, not a replacement for, "Autonomy boundaries"
above: qualification passing is evidence: it is never itself the
approval.

## Broker / product notes

Deriv **native API** (the `/trading/v1/options` REST+OTP+WebSocket flow),
trading **Multipliers** (`MULTUP` / `MULTDOWN`) — not traditional MT5 CFDs,
not classic binary options. See `src/trading/cfd/broker.py`'s docstring for
the confirmed connection flow and gotchas.

## Performance Engine — minimum tracked metrics

net return, expectancy, profit factor, win rate, average win / average
loss, R multiple, Sharpe, Sortino, Calmar, max drawdown, longest losing
streak, performance by strategy, performance by regime, performance by
session, long vs short, exposure, trade count — plus, per this revision,
portfolio-level expectancy/drawdown, concentration, and correlation/overlap
across simultaneously open positions.

## Failure Analysis — loss classification

normal statistical loss, wrong market regime, bad entry, strategy
mismatch, strategy degradation, spread/slippage problem, execution
problem, data problem, abnormal market/news event, excessive risk.

## Hard prohibitions

- No martingale
- No revenge trading
- No increasing risk because of a loss
- No increasing risk because a profit target hasn't been hit yet
- No overtrading to hit a trade-count target, and no lowering entry quality
  to manufacture trades
- No splitting one thesis into multiple orders to evade a risk ceiling
- No treating correlated positions as diversified because their instrument
  names differ
- No hot-editing a live strategy without going through validation first
- No modifying a strategy's version/parameters mid-Qualification
- No use of future data / lookahead leakage
- No promoting a strategy because backtest looked good over one lucky
  window
- **No deliberately trading an account's balance down or up to hit a
  target number.** (This directly forbids anything like the existing
  `scripts/burn_demo_balance.py`.)
- No AI-initiated action that raises a hard risk ceiling, moves up the risk
  ladder, enables real money, or promotes a strategy past PAPER — see
  "Autonomy boundaries" above; these always need a human

## Long-run design loop

```
Observe -> Understand Market -> Find Opportunities (multi-market, multi-strategy)
  -> Allocate -> Size Risk (per-position/thesis/correlated/portfolio)
  -> Execute -> Hold Adaptively -> Protect/Realize Profit -> Measure
  -> Diagnose -> Decay-Check -> Research -> Qualify -> Adapt -> Repeat
```

The AI does not need to be right 100% of the time. It needs to: be wrong
less often, lose less when wrong, exploit real edge well when it has one
(or several, weighted by how well each fits current conditions, across
multiple markets at once), know when *not* to trade, let genuine winners
run instead of capping them uniformly, detect strategy decay early and act
on it within its own authority, and adapt faster than the market's edge
disappears — all without ever needing a human to sign off on making the
system safer, and without a human ever discovering the AI made the system
more aggressive without asking first.

## Revision history

- **2026-09-19**: initial recording of the master vision, from the
  project's original brief.
- **2026-09-20**: user flagged that the first implementation pass had
  interpreted this too narrowly — as a single-winner strategy selector
  with every lifecycle change, including routine demotions, requiring
  manual human approval. This revision added: explicit multi-strategy
  Portfolio/Allocation as a pipeline stage; an "Autonomy boundaries"
  section distinguishing what the AI may decide unilaterally (anything
  that only reduces risk/exposure) from what always needs a human; a
  richer target regime taxonomy (volatility dimension, explicit
  "unstable" condition); and an explicit statement that the current EMA
  crossover strategy's backtest numbers are one early candidate's
  result, not a ceiling on the architecture.
- **2026-09-20 ("Revision 3")**: the user and GPT independently converged
  on a fuller picture of the same architecture and asked for it recorded
  as the explicit source of truth before further development. This
  revision adds, on top of the above: a precise risk model
  (per-position/per-thesis/correlated/portfolio/leverage ceilings, and
  what "risk 1%" actually means); explicit permission and support for
  multiple concurrent independent positions across multiple markets and
  strategies; an adaptive holding-period and exit philosophy (no fixed
  holding period, no uniform fixed take-profit, trailing stop and partial
  close required, initial risk decoupled from realized upside); no fixed
  daily trade-count target either direction; a qualified risk ladder for
  any risk increase, always human-gated at the top; drawdown-tiered risk
  reduction and smoothed-equity/high-water-mark logic against risk
  oscillation; portfolio-level risk analysis and an explicit
  portfolio-level NO TRADE gate; a strict Research-vs-Qualification
  environment separation (frozen strategy version during qualification);
  execution realism requirements (realistic backtest costs, idempotency,
  reconciliation, isolating manual/foreign trades from the system's own
  equity); and a measurable Qualification Gate that must be demonstrated,
  not asserted, before real money is ever enabled. The system must never
  again be interpreted back down into a single-strategy, fixed-horizon,
  or minimum-risk bot.

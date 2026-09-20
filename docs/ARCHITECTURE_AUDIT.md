# Architecture Audit vs. Master Vision

Audit date: 2026-09-19. Compares the current codebase (see `docs/VISION.md`
for the target) against what actually exists on
`claude/ai-trading-manager-deriv-pmay2v`. The audit itself is read-only —
no trading logic was changed while writing it.

**Status as of the last entry below: all five phases of the original
roadmap (Phase 0 through Phase 5) are complete, and the pipeline has now
been exercised against the real Deriv demo account** -- but see
"Revised gap analysis (2026-09-20)" below: `docs/VISION.md` was revised
the same day to correct a too-narrow reading of the original brief, and
three structural gaps against the *revised* vision are now open,
tracked there.

## Revised gap analysis (2026-09-20)

`docs/VISION.md` was revised after the user flagged that Phases 2-5 built
a **single-winner strategy selector with human-gated everything**, when
the actual intent was a **portfolio manager that can run multiple
strategies at once and demote/pause on its own initiative** (never
promote, never raise risk, on its own). Comparing what exists against the
revised vision:

1. **No multi-strategy Portfolio/Allocation stage.**
   `trading.cfd.selector.select_for_entry()` picks exactly one ACTIVE
   strategy per regime (and `strategy_registry.set_state()`/`register()`
   actively *enforce* "at most one ACTIVE per regime" as an invariant --
   the opposite of what's needed now). There's no concept of splitting
   allocation/risk budget across several simultaneously-suited
   strategies, no weighting by conviction or recent performance. This is
   the biggest structural gap against the revised pipeline's explicit
   "Portfolio / Allocation Decision" stage.
2. **No autonomous demotion.** `trading.cfd.failure_analysis.
   detect_degradation()` only *reports* a degraded strategy;
   `trading.cfd.manager_report` only *recommends* the
   `promote-strategy ... PAUSED` command. Nothing in the codebase ever
   calls `strategy_registry.set_state()` itself. Per the revised
   "Autonomy boundaries" section, demotion/pause/allocation-reduction on
   detected decay should happen automatically (logged, explained, never
   silent) -- promotion past PAPER is the only lifecycle direction that
   should still require a human.
3. **Regime taxonomy is narrower than the target.**
   `trading.cfd.regime.classify_regime()` only returns
   trending/ranging/unknown from a single ADX reading. The revised
   vision wants a volatility dimension (high/low) alongside trend
   strength, and an explicit "unstable, don't trade" condition distinct
   from "ranging" -- not built yet.

Not gaps, already correctly built and unaffected by the revision: the
Risk Governor boundary (AI never raises risk or crosses a hard limit --
already true, this revision only *adds* explicit permission to lower
risk autonomously, it doesn't loosen the ceiling side at all), the
Strategy Registry's lifecycle states and audit trail, Research Lab's
Backtest->Walk-Forward->Monte Carlo gate landing candidates at VALIDATED
only, Paper Trading's simulated execution, and the virtual equity
capital model. These all still match the revised vision as-is.

## Progress log

- **2026-09-19 — Phase 0 + Phase 1 done.** Virtual equity model
  (`trading/cfd/capital.py`), the min-stake SKIP TRADE guard
  (`risk.py`), `scripts/burn_demo_balance.py` deprecated (refuses to run
  without an explicit override flag, removed from the manual-command
  workflow), Trade Database (`trading/cfd/trade_log.py`,
  `state/cfd_trades.jsonl`), and Performance Engine
  (`trading/cfd/performance.py`, `cfd_cli.py performance`) are all live.
  `scheduler.py` now also actually calls `risk.register_open()`/
  `register_close()` (it didn't before this change — the daily-loss
  circuit breaker was dead code in production until now).
- **2026-09-19 — Phase 2 done.** Strategy Registry
  (`trading/cfd/strategy_registry.py`, `state/cfd_strategy_registry.json`)
  with the full lifecycle (`RESEARCH -> CANDIDATE -> VALIDATED -> PAPER ->
  ACTIVE -> PAUSED -> RETIRED`), enforced one-stage-at-a-time transitions,
  and a required-reason audit trail on every promotion/demotion.
  `scripts/seed_strategy_registry.py` registered the two existing
  strategies (`ema_crossover@v1` grandfathered into `ACTIVE`,
  `donchian_breakout@v1` into `CANDIDATE`). `scheduler.py` initially
  resolved which strategy to trade from the registry (superseded the same
  day by Phase 3's per-regime selection -- see below) instead of
  hardcoding `EmaCrossoverStrategy()`. `cfd_cli.py list-strategies` /
  `promote-strategy` manage it. The registry does not yet include the
  actual validation pipeline that's meant to gate promotion (walk-forward,
  Monte Carlo/stress test, real paper trading) -- that's still Phase 4;
  promotion today is a deliberate manual action, not an automatic gate.
- **2026-09-19 — Phase 3 done.** Market Regime Engine
  (`trading/cfd/regime.py`): classifies each instrument's own candles as
  `trending`/`ranging`/`unknown` via ADX, independently per instrument
  (no single reference symbol works across forex/gold/synthetics the way
  SPY does for the stock system's `trading/regime.py`). Strategy Selector
  (`trading/cfd/selector.py`): matches that regime against `ACTIVE`
  strategies' new `suited_regimes` field and picks the one that fits, or
  returns an explicit NO TRADE. `strategy_registry.py` now enforces "at
  most one ACTIVE strategy per regime" at promotion time
  (`register()`/`set_state()`), replacing Phase 2's stricter "at most one
  ACTIVE strategy, period" (`get_active_strategy()`, removed -- its
  premise no longer held once multiple ACTIVE strategies partitioned by
  regime became valid). `scheduler.py` resolves the entry strategy per
  instrument, per run (not once globally), and always manages an existing
  open position with the exact strategy version that opened it (tagged in
  its trade metadata), regardless of what's `ACTIVE` now. Both registered
  strategies are trend-following (`suited_regimes=["trending"]`), so this
  mostly acts as a NO TRADE gate during `ranging` markets today -- still
  no mean-reversion/range strategy in the pool to fill that gap.
- **2026-09-19 — Phase 4, first slice: Failure Analysis done.**
  `trading/cfd/failure_analysis.py` (`cfd_cli.py failures`): classifies
  every losing trade as `normal_statistical_loss`, `excessive_risk` (loss
  notably exceeded its budgeted `risk_amount` -- R multiple <= -1.5), or
  `regime_mismatch` (entry regime wasn't in the strategy's
  `suited_regimes` -- only reachable for a trade predating the regime
  gate). Also `detect_degradation()`: flags a registered strategy whose
  recent trades' expectancy has fallen sharply vs. its own earlier
  history (never auto-acted on -- a human still has to
  `promote-strategy ... PAUSED`). Fixed a real gap this surfaced:
  `scheduler.py` computed each entry's regime (Phase 3) but never
  persisted it onto the trade record -- now every new/closed trade
  carries the `regime` it was opened in, so `performance.py`'s
  `by_regime` breakdown finally has real data too. Three of the vision's
  loss categories (abnormal market/news event, execution problem, data
  problem) are still not classified -- no news/latency/data-quality
  signal exists to base them on, so they're deliberately never guessed at
  (see "Other vision requirements not yet met" below).
- **2026-09-19 — Phase 4 complete.** `trading/cfd/validation.py`:
  walk-forward (fixed params re-tested across sequential TEST folds,
  reporting fold-consistency and worst-fold drawdown) and Monte Carlo
  (reshuffles a backtest's own trades into 1000s of random orders,
  reporting ruin probability + equity/drawdown percentiles). `trading/
  cfd/research_lab.py` (`scripts/research_cfd_strategy.py`, the
  `research-strategy` manual-command): runs a strategy's parameter grid
  through the full Backtest -> TEST -> Walk-Forward -> Monte Carlo gate
  and auto-registers any candidate that clears every stage as `VALIDATED`
  -- never higher; PAPER and ACTIVE still need a human's
  `promote-strategy` call. `trading/cfd/operating_mode.py`
  (`cfd_cli.py set-mode`): Defensive/Normal/Aggressive/Recovery as fixed
  `risk_per_trade`/`max_open_positions` multipliers, hard-capped by
  `CFD_MAX_RISK_PER_TRADE_CEILING`; Defensive and Recovery share the same
  conservative multiplier by design (Recovery is never "bet bigger to
  catch up"). `scheduler.py` now applies the current mode to every
  run's risk sizing. Mode *selection* is still manual -- an AI deciding
  when to enter Recovery/Defensive on its own is Phase 5's job. This
  closes out every item docs/ARCHITECTURE_AUDIT.md's original Phase 4
  bullet named.
- **2026-09-19 — Phase 5, scoped and closed within that scope.** Two
  pieces, both read as "what does an AI Trading Manager actually get to
  decide on its own, vs. what a human must still approve" -- the same
  question every earlier phase already answered the same way (Risk
  Governor over the AI, no hot-editing without validation, no promotion
  on backtest results alone):
  - **Paper Trading** (`trading/cfd/paper_trading.py`, `state/
    cfd_paper_trades.jsonl`, `cfd_cli.py paper-performance`): every
    `PAPER`-state strategy now actually runs -- same regime-gated
    selection logic as `ACTIVE`, on the same live candles, simulated
    fills only. Before this, `PAPER` was a lifecycle label with no
    operational behavior behind it (flagged as a real gap in the Phase 4
    entry above); this closes it.
  - **AI Trading Manager Report** (`trading/cfd/manager_report.py`,
    `cfd_cli.py manager-report`): the layer that actually reads across
    the Trade Database, Paper Trading log, and Strategy Registry, and
    turns Failure Analysis's degradation flags, Research Lab's
    `VALIDATED` candidates, and Paper Trading's results into concrete,
    named `cfd_cli.py` commands -- e.g. "pause this degraded `ACTIVE`
    strategy," "start paper trading this `VALIDATED` candidate," "this
    `PAPER` strategy looks ready for `ACTIVE`." This is the automated
    synthesis step docs/VISION.md's pipeline implies but never
    named outright.

  **What Phase 5 deliberately did NOT build: an AI that autonomously
  executes lifecycle changes** (pausing/promoting/retiring a strategy on
  its own). Every recommendation above still requires a human to run the
  named command -- doing otherwise would be exactly the
  AI-overrides-the-Risk-Governor / hot-edit-without-validation pattern
  docs/VISION.md forbids, the same principle Phases 2-4 already built
  around (Strategy Registry transitions always need a reason; Research
  Lab only ever lands a candidate at `VALIDATED`, never higher). What
  *is* fully automated, unchanged from Phase 3: BUY/SELL/NO TRADE and
  strategy selection among already-`ACTIVE` entries, every run, no human
  in that loop -- because that's the part of "the AI decides" the vision
  actually asks for; which strategies get to be `ACTIVE` in the first
  place stays a human's call.

  Also worth being explicit about: this AI Trading Manager is a
  deterministic, rule-based synthesis layer -- not an LLM reasoning over
  the data. Nothing here writes to the registry, applies a mode change,
  or acts autonomously between runs on its own initiative. If an LLM
  (e.g. a scheduled Claude session, mirroring the stock system's
  "Ongoing news monitoring" routine -- see this README's stock section)
  should periodically read `manager-report`'s output and either act
  within a narrow, pre-authorized scope or flag larger decisions to the
  user, that's a deliberate *operational* choice to set up later, not
  something this phase's code does on its own.

- **2026-09-19 — First live runs against the real Deriv demo account.**
  Triggered `CFD Manual Command` (`status`, `list-strategies`) and
  `CFD Trading` (the actual scheduler, twice) via GitHub Actions
  workflow_dispatch. Results:
  - `status` connected and read the real account: broker balance
    $3,169.49 (not Deriv's $10,000 default -- this account has prior
    testing history from before this architecture, including the
    now-deprecated `burn_demo_balance.py`).
  - First scheduler run: `broker_baseline` correctly recorded at
    3169.49, `capital_floor` correctly set to 100.0 (virtual). Committed
    `state/cfd_bot_state.json` with exactly those values -- Phase 0's
    core fix confirmed working against live data, not just unit tests.
  - `status` afterward correctly showed broker balance vs. virtual
    equity as two distinct, labeled numbers.
  - Second scheduler run: no state changes at all -- baseline's set-once
    guard held, and no ACTIVE strategy's regime matched at that moment
    (a correct NO TRADE, not a failure). No exceptions in either run.
  - `frxXAUUSD`/`frxEURUSD`/etc. candle fetches succeeded with no
    "market closed" errors -- resolved the README's prior "still not
    validated" note about forex/gold instruments specifically (see that
    file's CFD section). On that basis, `cfd-trading.yml`'s cron
    schedule (hourly, weekdays) was enabled -- previously commented out.
  - Not yet exercised live: an actual entry (no regime matched an
    ACTIVE strategy's `suited_regimes` during these two runs), Paper
    Trading (nothing is in `PAPER` state yet), Research Lab's live-data
    path (`research-strategy` was built and unit-tested but not run
    against real fetched history), and `manager-report`/`failures`
    with anything but empty data. These will only be exercisable once
    real trade history accumulates from the now-enabled schedule.

- **2026-09-19 — Three real bugs found by a second, independent code
  review, all confirmed and fixed same-day.** The review (an external
  pass, not self-caught) flagged several items; most restated things
  already fixed in earlier entries above (virtual equity, regime/
  selector/degradation/research-lab existing at all) and were outdated.
  Three were real and are now fixed:
  1. **Daily-loss circuit breaker never actually tracked a full day.**
     `CfdRiskManager._daily_start_equity`/`_halted` lived only in memory,
     and `scheduler.py` constructs a fresh `CfdRiskManager` every run (a
     new process each time) -- so the breaker silently reset every
     ~hour instead of accumulating loss across a real calendar day.
     Fixed: `trading.cfd.state.get_daily_risk_tracking`/
     `set_daily_risk_tracking` persist start-of-day equity and the
     halted flag, keyed to the current UTC date; `CfdRiskManager` gained
     `daily_start_equity`/`initially_halted` constructor params (both
     optional, backward compatible) to receive them.
  2. **`capital_floor` auto-set to the exact starting balance could
     permanently and silently halt trading.** `scheduler.py` used to set
     `capital_floor = equity` on the very first run. On a small account,
     one ordinary loss (e.g. -$1 at 1% risk on $100) drops equity below a
     floor that tight, and there was no `set-floor`/`clear-floor` command
     for the CFD system (unlike the stock system's `cli.py`) -- so once
     breached, new entries stayed blocked forever with no way to recover
     short of hand-editing the state JSON. Fixed: the floor is never set
     automatically now (stays `None`/no protection until a human
     deliberately chooses one); `cfd_cli.py set-floor`/`clear-floor`
     added; `status`'s growth-since-start figure decoupled from the floor
     entirely (computed from `CFD_VIRTUAL_STARTING_CAPITAL` directly, so
     it works whether or not a floor is ever set). The live account's
     pre-existing auto-set floor (exactly 100.0, from the first live run
     recorded in the entry above) was cleared as part of applying this
     fix, not just the code path that created it.
  3. **The actually-validated Donchian breakout parameters were never
     registered.** `scripts/sweep_cfd_risk_breakout.py` (see git commit
     d1a86d4) found a genuinely robust candidate (`entry_window=80,
     exit_window=15, atr_stop_mult=3.5, atr_target_mult=6.0` -- TRAIN
     cagr=7.9% maxdd=-22.4%, TEST cagr=9.8% maxdd=-17.6%, the first
     candidate all session where TRAIN and TEST agreed in both sign and
     rough magnitude) -- but `scripts/seed_strategy_registry.py` had only
     ever registered `donchian_breakout@v1` with `breakout.py`'s
     unvalidated *placeholder* params (`entry_window=30` etc.), and
     nothing ever registered the real ones. The validated strategy that
     "Claude already tested and found better" was sitting nowhere in the
     system a human could act on. Fixed: `donchian_breakout@v2` now
     carries the actually-validated params as `VALIDATED`; `v1` is
     `RETIRED` (superseded, not deleted -- audit trail intact).

  All three fixes are unit-tested (backward compatible with every
  existing `CfdRiskManager`/state test) and applied to the live account's
  actual state files, not just the code going forward.

  Everything else below is still an accurate account of what's missing.

## Executive summary

The repo has two systems in it: a mature stock system (Alpaca) and a
younger, still-experimental CFD/Deriv system. **All of the vision's
"AI Trading Manager" layer is missing** — what exists today for CFD trading
is one fixed rule-based strategy at a time (EMA crossover, or an unvalidated
Donchian breakout), chosen manually via config, with no regime-driven
selection, no self-diagnosis, no strategy lifecycle, and no research loop.
The Deriv connection layer, risk-manager skeleton, and backtest/validation
*discipline* (train/test split, reject-on-overfit) are solid and worth
keeping — they're the right foundation to build the AI layer on top of,
not a reason to start over.

Two issues need a decision before any further development, because they
actively conflict with rules the user just set as non-negotiable:

1. **No virtual-equity model exists at all.** `CfdRiskManager`,
   `cfd/state.py`, and `cfd/scheduler.py` size every trade and every
   capital-floor check off the **raw Deriv broker balance**. On first run,
   `set_capital_floor(equity)` records whatever the broker balance
   literally is as the floor — if that's still ~$10,000 (or partway burned
   down), every risk calculation in the system is currently ~100x too large
   relative to the user's real $100 intent. This is exactly the
   "ห้ามใช้ $10,000 เป็นฐานสำหรับ position sizing" rule.
2. **`scripts/burn_demo_balance.py` exists and has been run.** It
   deliberately opens biased positions (stop-loss reachable quickly,
   take-profit far away, explicit comment "preserving the loss bias") to
   force the demo account's balance down from $10,000 toward $100, and per
   its own docstring/git history it partially succeeded (e.g. "$5700 ->
   $2300 over ~22 rounds") before dying on a dropped connection. This is
   precisely what the new master vision forbids
   ("ห้ามจงใจเทรดให้ Demo $10,000 ลดลงเหลือ $100"). It predates this vision
   and was a deliberate, documented workaround at the time — but it should
   not run again, and the demo account's current balance/history should be
   treated as contaminated for any performance analysis.

See "Decisions needed" at the end.

## What already exists and is worth reusing

| Piece | File(s) | Verdict |
|---|---|---|
| Deriv PAT auth + WebSocket connection flow | `cfd/broker.py` | **Keep.** Confirmed live end-to-end (connect/buy/portfolio/sell), documents real API gotchas (`underlying_symbol` not `symbol`, `account_type` not `is_virtual`, per-instrument multiplier caps). This is hard-won knowledge; do not rediscover it. |
| Demo/real account safety gate | `cfd/broker.py connect()` | **Keep.** Picks `account_type == "demo"` unless `CFD_ALLOW_LIVE_TRADING` is explicitly true; workflows hardcode it `false` too (defense in depth). Matches the vision's "Risk Governor above the AI" spirit for the live/demo boundary specifically. |
| Candle fetching | `cfd/broker.get_candles` | **Keep**, with a known limit: Deriv only serves ~3 months of M15 history server-side (H1 goes back ~11 months) — already why the strategy runs on H1. |
| Order placement / position close | `cfd/broker.submit_multiplier_order`, `close_position` | **Keep.** |
| Risk manager skeleton (position sizing, daily-loss halt, capital floor) | `cfd/risk.py` | **Keep the shape, replace the equity source.** Sizing math (`stake_and_limits`) and the daily circuit breaker are reasonable and match the vision's "Risk Governor" role structurally. It currently takes `equity` as raw broker balance — needs to take **virtual equity** instead (see decisions). |
| Backtest engine + TRAIN/TEST discipline | `cfd/backtest.py`, `scripts/optimize_cfd_strategy.py` | **Keep as the seed of the Validation stage.** Already enforces: winner must beat untouched defaults on TEST, not just clear a floor; ranks top-N TRAIN candidates by TEST performance, not TRAIN performance (caught a real overfit case per the README). This is walk-forward-*adjacent* but not full walk-forward or Monte Carlo yet — see gaps. |
| Two CFD strategies | `cfd/strategy.py` (EMA crossover, validated), `cfd/breakout.py` (Donchian, **unvalidated**) | **Keep both as pool members**, but breakout needs its own TRAIN/TEST run before it's trusted (script `optimize_cfd_breakout.py` already exists for this). |
| State/pause/exclude-instrument plumbing | `cfd/state.py`, `scripts/cfd_cli.py`, `cfd-manual-command.yml` | **Keep.** Reasonable manual-override surface; same pattern as the stock system's `cli.py`. |
| Stock-side regime classifier | `trading/regime.py` | **Reusable pattern, not reusable code.** It's a simple SMA-slope bull/bear/neutral classifier over one reference symbol (SPY) — a fine *starting shape* for a regime engine, but the CFD side needs its own (per-instrument, since there's no single "SPY of forex/synthetics") and a richer regime taxonomy (trend/range/high-vol/low-vol at minimum) to actually drive strategy selection the way the vision wants. |
| Stock-side ratchet / bucket capital management | `risk/ratchet.py`, `execution/buckets.py` | **Reusable pattern** for "bank profit as equity grows" — same idea the vision's capital model needs (floor ratchets up, never down), just needs porting to work off virtual equity on the CFD side. |
| GitHub Actions scheduling pattern | `.github/workflows/*.yml` | **Keep.** Hourly run, commit-state-back-to-repo, manual-dispatch command workflow — all directly reusable for whatever the new pipeline needs to run on a schedule. |

## Gap map against the target pipeline

```
Deriv Market Data          -> EXISTS (broker.get_candles)
Market Regime Engine       -> DONE for Phase 3's scope (trending/ranging/unknown per instrument via ADX) -- taxonomy is deliberately narrow (only what the 2-strategy pool can act on); no volatility/multi-timeframe dimensions yet
AI Trading Manager         -> DONE for what's automated by design (BUY/SELL/NO TRADE + strategy selection among ACTIVE entries, every run, no human in that loop -- trading.cfd.selector) PLUS a synthesis/reporting layer (trading.cfd.manager_report) that turns Performance/Failure Analysis/Research Lab/Paper Trading results into concrete recommended commands. Strategy lifecycle changes (pause/promote/retire) are deliberately NOT autonomous -- always a human's `promote-strategy` call, per docs/VISION.md's rule against hot-editing/promoting without validation. This is a deterministic rule-based layer, not an LLM reasoning over the data -- see the Phase 5 progress log entry.
Strategy Selector          -> DONE for Phase 3's scope (regime-matched against ACTIVE strategies' suited_regimes); only ever picks among trend-following strategies today since that's all that's registered
BUY/SELL/NO TRADE          -> DONE for new entries (Phase 3): no ACTIVE strategy suited to the current regime is now an explicit, logged NO TRADE decision, not just an absence of signal. Not yet persisted to the Trade Database as its own record (only closed trades are) -- see "Other vision requirements not yet met" below.
Risk Governor              -> PARTIAL (CfdRiskManager is now sized off virtual equity and has a min-stake SKIP TRADE guard -- Phase 0, done; still nothing stops a future AI Trading Manager layer from bypassing it, because that layer doesn't exist yet)
Execution Engine           -> EXISTS (scheduler.py + broker.py; now also actually drives CfdRiskManager's register_open/register_close, which it didn't before)
Deriv                      -> EXISTS
Trade Database             -> DONE for Phase 1's scope (trade_log.py, state/cfd_trades.jsonl) -- one known gap: a trade Deriv auto-closes via stop-loss/take-profit is only priced exactly when it's the sole one that closed between two runs; simultaneous external closes log with pnl=null rather than a guessed split (no profit_table API integration yet -- see "Still not validated" thread in the CFD README section)
Performance Engine         -> DONE for Phase 1's scope (performance.py, `cfd_cli.py performance`): net return, expectancy, profit factor, win rate, avg win/loss, R multiple, Sharpe, Sortino, Calmar, max drawdown, longest losing streak, by-strategy/regime/session/side breakdowns, exposure. by_regime is schema-ready but always "unknown" until the Market Regime Engine (Phase 3) exists.
Failure Analysis            -> PARTIAL: loss classification + strategy degradation detection DONE (trading.cfd.failure_analysis, `cfd_cli.py failures`), covering normal_statistical_loss/excessive_risk/regime_mismatch. abnormal market/news event, execution problem, and data problem are NOT classified -- no news/latency/data-quality signal exists to base them on, so they're never guessed at (see below)
Research / Improvement Lab -> DONE for Phase 4's scope (trading.cfd.research_lab, scripts/research_cfd_strategy.py): searches an existing strategy class's parameter grid, runs every candidate through Backtest->TEST->Walk-Forward->Monte Carlo, auto-registers passing ones as VALIDATED (never higher). No new strategy LOGIC is generated (no code synthesis) -- "candidate" means a new parameter set for a strategy class already in trading.cfd.strategy_registry.STRATEGY_CLASSES, not a genuinely new strategy family (that still needs a human to write the class, e.g. a future mean-reversion strategy).
Validation                  -> DONE (Phase 4 + Phase 5): walk-forward (fixed-params consistency across sequential folds) and Monte Carlo/stress test (trade-reshuffle ruin-probability + drawdown/equity percentiles), pure functions over existing backtest output, wired into Research Lab's auto-gate (Phase 4); PAPER now has real operational meaning via trading.cfd.paper_trading (Phase 5), not just a label. PAPER->ACTIVE is still always a human's `promote-strategy` call -- by design (docs/VISION.md's rule against promoting without validation), not a gap.
Strategy Registry            -> DONE (Phase 2 + Phase 4): name@version, full lifecycle, enforced transitions, audit trail (Phase 2); now also a real automated path feeding it (Research Lab, Phase 4) that lands candidates at VALIDATED. PAPER->ACTIVE promotion is still always a human decision -- by design, not a gap (see docs/VISION.md's rule against promoting on backtest results alone).
```

## Other vision requirements not yet met

- **Three Failure Analysis categories are unclassifiable today**:
  abnormal market/news event needs a news feed, execution problem needs
  order latency/fill-quality data, data problem needs data-quality checks
  on the candles used -- none of this project's current data supports
  any of them, so `failure_analysis.classify_loss()` never returns them;
  a trade that might be one of these lands in `normal_statistical_loss`
  instead of a fabricated specific cause.
- **Strategy pool breadth**: only Trend/Momentum (EMA crossover) and
  Breakout (unvalidated) exist for CFD, both tagged `suited_regimes=
  ["trending"]`. Missing: Mean Reversion, Volatility Expansion, Pullback,
  Multi-Timeframe -- there's a real, waiting slot for a "ranging" regime
  strategy (trading.cfd.selector.select_for_entry() already returns NO
  TRADE for that regime today, for exactly this reason).
- **NO TRADE decisions aren't persisted anywhere** (Phase 3): a regime
  gate skipping an instrument is logged (`logger.debug`/`logger.info`)
  but not written to the Trade Database -- only closed trades are. A
  future Failure Analysis / Research Lab asking "how often did we sit out
  a ranging market, and did that turn out to be the right call" has
  nothing to read yet. A lightweight decision log (separate from the
  Trade Database's closed-trade schema) is a reasonable Phase 4 addition,
  not built now to keep this phase's scope to what was asked.
- ~~**Operating modes**~~ — **done (Phase 4).** `trading/cfd/
  operating_mode.py` (`cfd_cli.py set-mode`) covers Defensive/Normal/
  Aggressive/Recovery as fixed, pre-approved `risk_per_trade`/
  `max_open_positions` multipliers, layered under
  `CFD_MAX_RISK_PER_TRADE_CEILING` (an absolute ceiling no mode may
  cross). Paused was already covered by the existing `paused` flag.
  Defensive and Recovery intentionally share the same conservative
  multiplier -- Recovery means smaller size under equity strain, never
  bigger size to chase losses back (see the module's docstring). No
  automatic mode SELECTION yet (e.g. auto-entering Recovery from a
  drawdown signal) -- that decision-making belongs to the future AI
  Trading Manager layer (Phase 5); today a human sets the mode.
- **Hard prohibitions**: no martingale/revenge-trading logic exists in the
  current code (good — nothing to remove), but there's also no explicit
  guard *preventing* a future change from introducing risk-scales-with-loss
  behavior. The stock system's `RiskManager.ladder` does the *opposite*
  (scales risk with *cushion above floor*, i.e. more risk only from house
  money) — a fine pattern, but worth calling out so it's never confused
  with "increase risk after a loss."
- ~~**Minimum order size vs. $100 accounts**~~ — **done (Phase 0).**
  `stake_and_limits()` now returns SKIP (0.0, 0.0, 0.0) when the
  risk-budgeted stake comes out below `CFD_MIN_STAKE`, instead of
  rounding it up past the configured risk.

## Decisions needed before writing more code

*(Resolved 2026-09-19: kept `scripts/burn_demo_balance.py` for history,
deprecated with a hard run guard; started with Phase 0 + Phase 1
together. Both now done — see Progress log above. Text below is kept
as the record of that decision.)*

1. **`scripts/burn_demo_balance.py`** — recommend: keep the file (it's
   useful documented history of a real API constraint: Deriv demo accounts
   can't be reset to an arbitrary balance), but mark it clearly as
   deprecated/do-not-run, and never invoke it again. Confirm you're OK with
   that, or want it deleted outright.
2. **Current demo account balance** — since it may be a partially-burned,
   partially-organic mix of values with no clean baseline, the virtual
   equity baseline should be captured fresh (whatever the demo balance is
   *right now*, recorded once as `BROKER_DEMO_BALANCE_baseline`) rather
   than trying to reconstruct history. Trade history from before the
   virtual-equity model existed should not be used for performance
   analysis.
3. **Build order** — the full vision is a large system. Proposed phase
   order (smallest safety-critical fix first, then building the pipeline
   outward):
   - **Phase 0 (safety fix, do first, small):** virtual equity model —
     `BROKER_DEMO_BALANCE` baseline + `VIRTUAL_STARTING_CAPITAL`, wired
     into `CfdRiskManager`, `cfd/state.py`, and `cfd_cli.py status`. Add
     the missing SKIP-TRADE-on-minimum-stake guard. Retire
     `burn_demo_balance.py`.
   - **Phase 1:** Trade Database + expanded Performance Engine (the vision
     needs real trade history before Failure Analysis or a Research Lab
     have anything to learn from).
   - **Phase 2:** Strategy Registry + lifecycle states, formalize the
     existing strategies (EMA crossover, Donchian breakout) as its first
     two registered entries.
   - **Phase 3:** Market Regime Engine for CFD instruments + Strategy
     Selector that picks a registered ACTIVE strategy by regime, with NO
     TRADE as an explicit selectable state.
   - **Phase 4:** Failure Analysis, walk-forward + Monte Carlo validation,
     Research Lab candidate generation, operating modes.
   - **Phase 5:** the "AI Trading Manager" decision layer proper (the part
     that actually reasons about regime/selection/self-diagnosis end to
     end), sitting on top of everything above.

Waiting for direction on which phase to start, and on the two burn-down
questions above, before touching any trading code.

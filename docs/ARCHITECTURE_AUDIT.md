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
three structural gaps against the *revised* vision were opened, tracked
there. **All three are now closed** -- see Progress log. `docs/VISION.md`
was then revised again the same day ("Revision 3") with a much fuller
risk/execution model -- see "Revision 3 gap analysis" immediately below.
Gaps #2 (risk model foundation), #1 (exit philosophy), #6-9 (execution
realism/attribution), #4-5 (drawdown de-risking/smoothed equity), #10
(Qualification Gate), and #3 (decision cadence -- an instrument can now
hold independent positions from more than one ACTIVE strategy, and the
scheduler runs every 15 minutes instead of hourly) are now closed, in
the user's chosen order -- see Progress log. Gap #11 (strategy pool
diversity) was attempted twice -- `mean_reversion` (Bollinger-Band
fade) and `rsi_reversion` (RSI+ADX fade, built by GPT to a spec from
this session and reviewed before merge) -- and both TRAIN/TEST grid
searches found no robust profitable parameterization, so both are
`RETIRED` rather than promoted. Two honest negative results, not a gap
this session could close by trying harder; it remains the one open
item.

## Revision 3 gap analysis (2026-09-20) -- read-only, nothing fixed yet

`docs/VISION.md`'s Revision 3 (the user's message converging with GPT's
independent read of the same architecture) is far more specific than
either prior revision about the risk model, exit philosophy, and
execution integrity a real Adaptive AI Trading Manager needs. This
section is the user-requested "point out every conflict before fixing
anything" pass -- every item below is verified against the actual code
(file/line, not a guess), ranked roughly by how much it matters, and
**none of it has been changed yet**.

1. ~~**Every registered strategy's take-profit is a fixed R-multiple,
   sent to Deriv as a whole-position hard limit order.**~~ **Closed
   2026-09-20** -- see Progress log below.
2. ~~**No portfolio-level, per-thesis, or correlated risk ceiling
   exists.**~~ **Closed 2026-09-20** -- chosen by the user as the first
   gap to fix, since it's the foundation the rest of Revision 3's risk
   model depends on. See Progress log below.
3. ~~**Only one open position per instrument, and only an hourly
   decision cadence.**~~ **Closed 2026-09-20** -- see Progress log
   below.
4. ~~**No automatic drawdown-tiered risk reduction.**~~ **Closed
   2026-09-20** -- see Progress log below.
5. ~~**No smoothed-equity / high-water-mark risk basis.**~~ **Closed
   2026-09-20** -- see Progress log below.
6. ~~**Backtests don't model spread, slippage, commission, financing/
   rollover, or price gaps.**~~ **Closed 2026-09-20**, with a correction:
   "no slippage" on stop/target fills turned out to already be CORRECT
   for this product (Deriv Multipliers guarantee exact stop/take-profit
   execution -- see broker.py's docstring), not an optimistic
   simplification. Spread and overnight financing were the two real,
   unmodeled costs -- see Progress log below.
7. ~~**`risk_per_trade` sizing has no slippage/execution buffer.**~~
   **Closed 2026-09-20** -- see Progress log below.
8. ~~**Manual or foreign broker activity would silently blend into
   virtual equity.**~~ **Closed 2026-09-20** -- see Progress log below.
9. ~~**Idempotency is real but partial -- attribution-loss window.**~~
   **Closed 2026-09-20** -- see Progress log below.
10. ~~**Qualification Gate is not consolidated into one measurable
    report.**~~ **Closed 2026-09-20** -- see Progress log below.
11. **Strategy pool is still 2 members, both trend-following, both on a
    single timeframe (H1).** Attempted twice, 2026-09-20, still open --
    see Progress log below. Two third-strategy candidates, both
    structurally a mean-reversion/fade rather than trend-following, were
    built and run through their own TRAIN/TEST grid searches (~2 years
    of H1 forex/gold data): `mean_reversion` (Bollinger-Band fade, 81
    combinations, **zero** cleared CAGR>0 with drawdown within the -25%
    cap) and `rsi_reversion` (RSI+ADX fade, built by GPT to a spec from
    this session and reviewed before merge, 243 combinations, only 1
    cleared the cheap TRAIN gate and it failed out-of-sample as
    `[OVERFIT]`). Both honest negative results, not bugs, so both
    `mean_reversion@v1` and `rsi_reversion@v1` are `RETIRED`, not left
    as misleadingly-still-viable `CANDIDATE`s. The "ranging" regime is
    back to having zero suited `ACTIVE` or `CANDIDATE` strategy --
    neither Bollinger-Band nor RSI+ADX fading shows a usable edge on
    this data, but that's evidence against two implementations, not
    proof no ranging-regime edge exists here; a session/time-of-day
    approach, a different timeframe, or a different data source are all
    still open territory. The pool is also still single-timeframe (H1).
    4 configured instruments and `CFD_MAX_OPEN_POSITIONS` (now counting
    distinct (instrument, strategy) slots, not instruments -- see gap
    #3) mean the *machinery*
    for holding several concurrent independent positions already exists
    and isn't itself a gap.

**Not gaps -- already consistent with Revision 3, worth stating so they
don't get "fixed" into something worse:** no fixed daily trade-count
exists anywhere in the code (trade frequency is already purely
signal-driven, never quota-driven); default `risk_per_trade` (1%) with
`CFD_MAX_RISK_PER_TRADE_CEILING` as a hard, human-only-raisable ceiling
already matches "growth from multiplication, not from bigger bets";
autonomous demotion (`decay_supervisor.py`) and portfolio allocation
(`portfolio_allocator.py`) from the prior revision already match "AI may
move risk down on its own, never up" and don't need to be revisited for
Revision 3 -- they compose with the ceilings above once those exist,
they don't conflict with them.

## Revised gap analysis (2026-09-20)

`docs/VISION.md` was revised after the user flagged that Phases 2-5 built
a **single-winner strategy selector with human-gated everything**, when
the actual intent was a **portfolio manager that can run multiple
strategies at once and demote/pause on its own initiative** (never
promote, never raise risk, on its own). Comparing what exists against the
revised vision:

1. ~~**No multi-strategy Portfolio/Allocation stage.**~~ **Closed
   2026-09-20** -- see Progress log below. `strategy_registry.set_state()`
   /`register()` no longer enforce "at most one ACTIVE per regime";
   `trading.cfd.portfolio_allocator.compute_allocations()` weights every
   ACTIVE strategy by recent performance, and `trading.cfd.selector.
   select_for_entry()` picks among regime-suited matches by that weight
   instead of raising.
2. ~~**No autonomous demotion.**~~ **Closed 2026-09-20** -- see Progress
   log below. `trading.cfd.decay_supervisor.run_autonomous_demotion()`
   now calls `strategy_registry.set_state()` itself on every scheduler
   run for any `ACTIVE` strategy `detect_degradation()` flags, with no
   human in the loop for this (risk-reducing) direction.
3. ~~**Regime taxonomy is narrower than the target.**~~ **Closed
   2026-09-20** -- see Progress log below. `trading.cfd.regime` now adds
   a volatility dimension (`classify_volatility()`, ATR% vs. its own
   recent median) and an explicit `UNSTABLE` condition (`classify_regime()`)
   distinct from `RANGING`.

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

- **2026-09-20 — Revised gap #2 ("no autonomous demotion") closed.**
  The user chose this as the first of the three revised-gap-analysis
  items above to fix. New module `trading/cfd/decay_supervisor.py`
  (`run_autonomous_demotion(trades)`) iterates every `ACTIVE` strategy,
  runs `failure_analysis.detect_degradation()` against it, and for any
  that comes back degraded, calls `strategy_registry.set_state(...,
  PAUSED, reason="autonomous demotion: ...")` itself -- the same audited
  lifecycle path (history entry, required reason) a human's
  `promote-strategy` command uses, just triggered automatically instead
  of by hand. `scheduler.py`'s `run_once()` now calls it at the very
  start of every run, before the Deriv connection is even opened (cheap,
  local, no network) and before the "no ACTIVE strategy" fail-fast check,
  so a strategy demoted this run is correctly excluded from selection the
  same run. `manager_report.py`'s degradation recommendation is now
  explicitly informational (`type` renamed
  `pause_degraded_strategy` -> `degrading_strategy_pending_autonomous_demotion`):
  it's surfacing something `decay_supervisor` already acted on or is
  about to on the next scheduler run, not something waiting on a human.
  This directly implements `docs/VISION.md`'s "Autonomy boundaries" --
  demotion only ever *lowers* risk/exposure, so it needs no human
  approval; promotion past `PAPER` still does and is untouched by this
  change. 6 new tests in `tests/test_cfd_decay_supervisor.py` (no-active
  → no demotions; degraded ACTIVE → demoted with correct audit trail;
  healthy ACTIVE → left alone; too little trade history → left alone;
  non-ACTIVE strategies never touched regardless of their trade history;
  only the actually-degraded one among several ACTIVE strategies gets
  demoted). Full suite: 251 tests passing. Gaps #1 (multi-strategy
  portfolio allocation) and #3 (richer regime taxonomy) from the revised
  gap analysis above are still open, not yet started.

- **2026-09-20 — Revised gap #1 ("no multi-strategy Portfolio/Allocation
  stage") closed.** The biggest of the three revised-gap-analysis items,
  tackled right after autonomous demotion. Two changes:
  1. `strategy_registry.register()`/`set_state()` no longer enforce "at
     most one ACTIVE strategy per regime" -- `_conflicting_active_entry()`
     and its call sites are gone. Several ACTIVE strategies can now share
     `suited_regimes` at once, which is the entire point of a portfolio
     manager rather than a single-winner selector.
  2. New module `trading/cfd/portfolio_allocator.py`
     (`compute_allocations(trades, active_entries)`) gives every ACTIVE
     strategy a weight (summing to 1.0) from its own recent trade
     history: `WEIGHT_FLOOR` (0.05) + `max(0, expectancy)` once it has
     `MIN_TRADES_FOR_WEIGHTING` (10) trades of its own, or just the floor
     below that -- so a fresh promotion or a losing strategy is never
     starved to zero by this stage alone (that's `decay_supervisor`'s
     job, via an explicit, audited demotion, never an incidental side
     effect of allocation math). `risk_scale_factor(weight, n_active)`
     turns a weight into a per-trade risk multiplier relative to the
     equal-weight baseline, capped at 1.0 -- allocation can only ever
     redistribute the existing risk budget toward the stronger performer,
     never raise any one strategy's risk past what `risk_per_trade`
     already allows. `risk.py`'s `stake_and_limits()` gained an optional
     `risk_per_trade_override` param (clamped to never exceed the
     configured `risk_per_trade`, enforced in the risk manager itself,
     not just trusted of the caller) to actually apply it.
     `selector.py`'s `select_for_entry()` now takes the allocation
     weights and picks the highest-weighted regime-suited match instead
     of raising `RuntimeError` on more than one. `scheduler.py` computes
     allocations once per run (on the roster left standing after
     autonomous demotion) and uses them both to pick which strategy gets
     a given instrument's entry and to scale that entry's risk. Per
     `docs/VISION.md`'s "Autonomy boundaries": shifting the existing
     budget between ACTIVE strategies only ever lowers or holds any one
     strategy's risk, never raises it -- so, like demotion, it needs no
     human approval. `manager_report.py`'s `build_report()` now also
     returns `allocation_summary` (the current weights) purely for
     visibility, and `cfd_cli.py manager-report` prints it.
  13 new tests (`tests/test_cfd_portfolio_allocator.py`) plus updates to
  `tests/test_cfd_strategy_registry.py`, `tests/test_cfd_selector.py`,
  `tests/test_cfd_risk.py`, and `tests/test_cfd_manager_report.py` to
  match the relaxed invariant and the new weighting/override behavior.
  Full suite: 265 tests passing. Only gap #3 (richer regime taxonomy)
  from the revised gap analysis remains open.

- **2026-09-20 — Revised gap #3 ("regime taxonomy narrower than the
  target") closed -- all three revised-gap-analysis items now done.**
  `trading/cfd/regime.py` gains a volatility dimension alongside the
  existing ADX-based trend read:
  - `classify_volatility(bars, atr_window, lookback, low_ratio,
    high_ratio)` reads the latest bar's ATR as a fraction of price
    against the *median* of its own trailing history (a ratio, not a
    fixed cutoff, so a low-volatility forex pair and a high-volatility
    Deriv synthetic index both get judged against their own normal) --
    returns `low`/`normal`/`high`/`unknown` (the last when there isn't
    yet `MIN_VOLATILITY_HISTORY`=10 valid readings to compare against).
  - `classify_regime()` keeps its existing signature and string return
    (every caller -- `scheduler.py`, `selector.py`, `paper_trading.py`,
    `TradeRecord.regime`, already-registered strategies'
    `suited_regimes` -- needed zero changes) but can now also return the
    new `UNSTABLE` label: a volatility spike (ratio >=
    `unstable_volatility_ratio`, 2.5x by default, deliberately a higher
    bar than `classify_volatility()`'s own "high") landing without a
    strong enough ADX trend to justify the risk. `UNSTABLE` only ever
    overrides what would otherwise be `RANGING` -- a strong trend
    (`TRENDING`) is never downgraded by volatility alone, since
    ATR-based stops already size for it. No registered strategy declares
    `suited_regimes=["unstable"]`, so today this is another explicit NO
    TRADE gate, same status `RANGING` had before any range-trading
    strategy existed.
  - Three new `Settings` fields (`CFD_REGIME_ATR_WINDOW`,
    `CFD_REGIME_VOLATILITY_LOOKBACK`, `CFD_REGIME_UNSTABLE_VOLATILITY_RATIO`
    -- same reasonable-but-unvalidated-default status as the existing ADX
    settings) wired into `scheduler.py`'s `classify_regime()` call.
  7 new tests in `tests/test_cfd_regime.py` (steady/low/high volatility
  reads, too-little-history → unknown, a genuine volatility-spike-without-
  trend fixture classified `UNSTABLE`, a volatile-but-trending fixture
  staying `TRENDING`, the unstable ratio threshold's configurability) --
  the 4 pre-existing regime tests pass unchanged. Full suite: 272 tests
  passing. All three revised-gap-analysis items are now closed; the
  system matches the revised `docs/VISION.md` architecture on every point
  that audit identified.

- **2026-09-20 — Revision 3 gap #2 ("no portfolio-level, per-thesis, or
  correlated risk ceiling") closed -- the risk-model foundation the user
  chose to build first.** New module `trading/cfd/portfolio_risk.py`
  implements the Portfolio Risk Governor docs/VISION.md's Revision 3
  requires, explicitly NOT satisfiable by counting positions:
  - `thesis_key(instrument, side)` -- two positions are the same
    underlying bet only if they share both; `CORRELATION_FACTORS`, a
    **static, explicitly documented-as-static** map (not a computed
    rolling correlation -- this project has no market-data
    infrastructure for that), gives each of today's four configured
    instruments a signed exposure to a `"usd"` factor (gold/EUR/GBP
    long = bet against USD; USDJPY long = bet USD strengthens, since USD
    is the base currency) -- `factor_exposures()` flips every sign for a
    short.
  - `check_new_position(open_positions, new_instrument, new_side,
    new_risk_amount, new_notional, equity, ceilings)` checks, in order,
    per-thesis, correlated (grouped by the *signed* direction of factor
    exposure, so a natural hedge on the same factor never inflates the
    figure -- verified by `test_natural_hedge_on_same_factor_does_not_
    inflate_correlated_risk`), total portfolio, and leverage/exposure
    ceilings, returning a human-readable rejection reason or `None` --
    the caller's job is to SKIP TRADE on rejection, same semantics as
    every other hard risk check in this codebase (min-stake-skip,
    daily-loss-halt). It never scales a position down to fit; the user
    explicitly asked for reject, not silent resizing.
  - Four new hard ceilings in `Settings`
    (`CFD_MAX_THESIS_RISK_PCT`=2%, `CFD_MAX_CORRELATED_RISK_PCT`=3%,
    `CFD_MAX_PORTFOLIO_RISK_PCT`=5% -- matching docs/VISION.md's own
    worked example of five independent 1% positions, `CFD_MAX_EXPOSURE_
    MULTIPLE`=10x) -- same human-only-raisable status as
    `CFD_MAX_RISK_PER_TRADE_CEILING`, stated as reasonable starting
    defaults, not yet empirically tuned.
  - `TradeRecord` (`trade_log.py`) gained a `thesis_key` field, tagged at
    entry time and copied through on every exit path (signal-exit and
    reconciliation) -- an explicit, audited tag in the trade record
    itself, not just a value recomputable later from instrument/side.
  - `scheduler.py` builds a live snapshot of every currently-open
    position from `state.list_open_trades()` (persisted across runs, not
    just positions opened this run) right after reconciliation, checks
    every new entry against it before submitting the order, and updates
    the snapshot in place as positions open/close within the same run so
    later instruments see the current total. Newly-stored open-trade
    metadata now also carries `multiplier` and `thesis_key`.
  - `backtest.py`'s `CfdBacktestEngine` got the identical check (same
    `PortfolioRiskCeilings`, defaulting to the live settings) applied
    across its own multi-symbol simulation loop, so a backtest result
    can no longer validate a scenario live trading's own Risk Governor
    would actually have rejected -- `ceilings` is constructor-overridable
    for testing a specific scenario deterministically.
  - `manager_report.py`'s `build_report()` gained a `portfolio_risk_
    summary` section (current thesis/correlated/portfolio/leverage
    utilization against every ceiling) for visibility -- purely
    informational, offline (equity approximated as starting_equity +
    realized net_return, since this command never connects to Deriv) --
    and `cfd_cli.py manager-report` prints it.
  30 new tests across `tests/test_cfd_portfolio_risk.py` (17, covering
  thesis/correlation/hedge/portfolio/leverage math in isolation),
  `tests/test_cfd_backtest.py` (+2, a correlated pair blocked and an
  uncorrelated pair allowed through, in a live multi-symbol backtest run),
  and `tests/test_cfd_manager_report.py` (+1). Full suite: 292 tests
  passing. Per the user's explicit instruction, position-count limits
  (`max_open_positions`) were never used as a substitute for any of the
  four new ceilings -- every one is checked in real risk dollars (or
  notional, for leverage), independent of how many positions that
  happens to be. Remaining Revision 3 gaps, in the user's stated order:
  #1 (exit philosophy), #6-9 (execution realism/attribution), #4-5
  (automatic drawdown de-risking + smoothed equity), #10 (consolidated
  Qualification Gate), #11 (strategy pool diversity), #3 (decision
  cadence -- deliberately last, not to be sped up before the risk
  foundation and execution safety are both in place).

- **2026-09-20 — Revision 3 gap #1 ("fixed take-profit caps every
  winner") closed.** New module `trading/cfd/exit_manager.py`
  (pure functions, no broker/event-loop dependency):
  - `TrailingStopState` + `update_trailing_stop()`: once a position has
    moved favorably by `CFD_TRAILING_ACTIVATION_R_MULTIPLE` (default
    1.0) times its ORIGINAL stop distance, a trailing stop activates and
    ratchets toward locking in more profit every run, trailing
    `CFD_TRAILING_ATR_MULTIPLE` (default 2.0) ATRs behind price --
    recomputed from the LATEST candle's ATR each run, not a value frozen
    at entry, so it adapts to current volatility. Never loosens once
    activated. Before activation, a position is protected exactly as
    before: Deriv's own initial `stop_loss_amount`.
  - `split_stake_for_partial_close()`: Deriv Multipliers don't support a
    true partial sell of one contract (unconfirmed anywhere in
    `broker.py`, and never assumed against a live account per this
    project's stated discipline) -- so "partial close" means splitting
    one entry's already risk-budgeted stake into two SEPARATE contracts
    at entry: a `"scalp"` leg (`CFD_PARTIAL_CLOSE_FRACTION`, default
    50%, keeping the strategy's own normal fixed target -- locks in some
    profit early) and a `"runner"` leg (the remainder, no *effective*
    fixed target). The runner leg still gets a real
    `take_profit_amount` sent to Deriv (proposal requests omitting
    take-profit aren't confirmed live either) but
    `CFD_RUNNER_BACKSTOP_MULTIPLE` (default 10x) wider than its own
    proportional target -- a rare catastrophic backstop, never the leg's
    real exit mechanism (the trailing stop and the strategy's own
    signal exit are). If either leg's stake would fall below
    `CFD_MIN_STAKE`, a single full-stake `"runner"` leg opens instead of
    forcing an invalid split -- the common case on a small account, and
    still a real fix (trailing-stop-managed, not fixed-TP-capped).
  - `broker.py` gained `open_positions_list()` (every open contract as a
    flat list, never collapsed by symbol -- `open_positions()`'s
    existing symbol-keyed dict would silently hide one leg of a split
    position). `scheduler.py`'s main loop now tracks positions by
    `{instrument: [legs]}` instead of one dict entry per instrument,
    manages each leg independently (shared strategy-signal exit check
    across all legs of one instrument, since they can only ever come
    from the same entry decision; trailing-stop check additionally for
    `"runner"` legs only), and `max_open_positions` still counts distinct
    INSTRUMENTS with any leg open, never raw contracts -- a split never
    silently doubles that ceiling's meaning.
  - `TradeRecord` gained a `leg` field (`"scalp"`/`"runner"`/`None` for a
    pre-existing trade); both legs share the same `thesis_key` and were
    already checked as one combined unit against the Portfolio Risk
    Governor (previous entry) before either was submitted.
  - `cfd_cli.py status`/`manager-report` switched to
    `open_positions_list()` too, so a human checking the live account
    sees both legs of a split position, not just one.
  **Known, disclosed follow-up, not fixed in this pass:**
  `backtest.py`'s `CfdBacktestEngine` and `paper_trading.py` still
  simulate the OLD single-fixed-target exit model -- their validation/
  forward-simulation numbers are now out of sync with what live trading
  actually does. Deliberately not rushed into this same change (the
  user's next queued layer, execution realism, is the right place to
  bring backtest/paper fidelity back in line with live behavior, rather
  than a hurried, undertested addition here). 18 new tests in
  `tests/test_cfd_exit_manager.py` covering the trailing-stop and split
  math directly; `run_once()` itself stays validated the same way as
  before (no unit test exists for it anywhere in this codebase -- it's
  broker-coupled and validated by live smoke-testing via GitHub Actions,
  not mocked). Full suite: 310 tests passing.

- **2026-09-20 — Revision 3 gaps #6-9 ("execution realism and
  attribution") closed.**
  - **Gap #7 (sizing buffer)**: `CfdRiskManager` gained
    `stake_safety_margin` (`CFD_STAKE_SAFETY_MARGIN`, default 0.97),
    applied to `risk_amount` itself (not just the derived stake) so the
    stop-loss-price-to-dollar-amount relationship Deriv actually enforces
    stays internally consistent at the smaller size. Wired into
    `scheduler.py`'s live `CfdRiskManager` only -- `backtest.py`'s own
    construction is untouched (defaults to 1.0/no change), since a
    backtest's fill price *is* the signal price by construction; the
    margin is specifically about the live entry-price gap between signal
    computation and actual Deriv fill.
  - **Gap #6 (backtest cost realism)**, with a correction to the original
    framing: Deriv Multipliers guarantee exact stop-loss/take-profit
    execution (`broker.py`'s own docstring), so "no slippage" on those
    fills was already correct, not optimistic. The two real, unmodeled
    costs -- spread and overnight financing -- are now supported in
    `CfdBacktestEngine` via `spread_pct`/`daily_financing_pct`
    (`CFD_BACKTEST_SPREAD_PCT`=0.05%, `CFD_BACKTEST_DAILY_FINANCING_PCT`
    =0.005%/day, both stated placeholders, not calibrated to live Deriv
    numbers -- no confirmed commission structure exists for this product
    beyond these two, so none was invented). Both default to 0.0 on the
    engine itself, preserving every existing unit test's exact-fill
    assertions unchanged; all 6 real script call sites
    (`research_cfd_strategy.py`, `optimize_cfd_strategy.py`,
    `optimize_cfd_breakout.py`, `sweep_cfd_risk*.py`) now pass the
    configured non-zero values explicitly, so real validation runs
    include these costs by default. Spread is deducted once per closed
    trade from that trade's own `pnl`; financing accrues directly against
    equity at every UTC day boundary a position stays open -- matters
    far more now that Revision 3 explicitly permits multi-day holds.
  - **Gap #9 (idempotency/attribution) + gap #8 (foreign positions)**,
    closed together with one mechanism: `trading.cfd.state` gained
    `set_pending_entry`/`get_pending_entries`/`clear_pending_entry` --
    `scheduler.py` now records intent (every leg's full metadata) right
    before submitting any order for an entry, and clears it right after,
    whether every leg succeeded or not. New `_reconcile_unknown_
    positions()` (called at the start of every run, before the
    Portfolio Risk Governor snapshot is built) splits every open
    contract with no local `tracked_open` metadata into two buckets:
    contracts matching a *stale* pending entry from a run that crashed
    between submitting an order and its state-file commit ever landing
    (a separate, later workflow step) are **adopted** -- full
    strategy/thesis/risk_amount attribution recovered, not lost; anything
    else is **foreign** -- never opened by this bot's own tracked intent
    at all. A foreign contract is never silently absorbed into this
    bot's own attribution: its instrument is auto-excluded from new
    entries (the existing, already-audited `excluded_instruments`
    mechanism -- a risk-reducing action, no human approval needed) and
    logged loudly for a human to investigate. Virtual equity's
    balance-derived nature means a foreign position's balance impact
    still reaches it (not solvable without a deeper per-trade balance
    API Deriv doesn't expose here) -- but it can no longer happen
    *silently*, which is what gap #8 actually asked for.
  20 new tests (`tests/test_cfd_risk.py` +3, `tests/test_cfd_backtest.py`
  +3, `tests/test_cfd_state.py` +3, `tests/test_cfd_scheduler.py` +7,
  plus 4 covering related edge cases). Full suite: 326 tests passing.
  Live-smoke-tested against the real Deriv demo account after the
  previous entry (gap #1) and again planned after this one, per the
  usual discipline for a scheduler.py change. **Not done in this pass,
  still an open, disclosed item**: `backtest.py`/`paper_trading.py`
  still simulate the pre-Revision-3 fixed-target exit model, not the
  new trailing-stop/partial-close one from gap #1 -- their validated
  numbers reflect realistic costs now, but not the new exit mechanism
  itself. Remaining Revision 3 work, in the user's stated order: #4-5
  (automatic drawdown de-risking + smoothed equity), #10 (consolidated
  Qualification Gate), #11 (strategy pool diversity), #3 (decision
  cadence -- still deliberately last).

- **2026-09-20 — Revision 3 gaps #4-5 ("automatic drawdown de-risking" +
  "smoothed equity") closed.** Two new modules:
  - `trading/cfd/smoothed_equity.py`: `update_smoothed_equity()` is an
    EMA that's deliberately ASYMMETRIC -- it damps how fast the
    sizing-equity figure catches up to a GAIN (`CFD_EQUITY_SMOOTHING_
    ALPHA`, default 0.3), but is capped at `min(ema, current_equity)` so
    it never lags a LOSS: on any drop it snaps immediately to the new,
    lower current equity. This directly matches docs/VISION.md's own
    framing ("don't use recent profit as an excuse to scale risk up
    fast") without slowing down how fast the system reacts to an actual
    loss, which every other protective check in this codebase (capital
    floor, daily-loss halt) already depends on being immediate.
    `update_high_water_mark()` is a simple ratchet -- the highest virtual
    equity ever observed, never decreasing.
  - `trading/cfd/drawdown_monitor.py`: `classify_drawdown_tier()` reads
    current equity against the high-water-mark and returns
    normal/moderate/deep/severe (`CFD_DRAWDOWN_MODERATE_PCT`=10%,
    `_DEEP_PCT`=20%, `_SEVERE_PCT`=30%, all illustrative, unvalidated
    defaults matching docs/VISION.md's own example tiers);
    `drawdown_risk_multiplier()` maps that to 1.0/0.75/0.5/0.0
    (`CFD_DRAWDOWN_MODERATE_MULTIPLIER`, `_DEEP_MULTIPLIER`) -- severe
    means every new entry's risk-budgeted stake computes to $0 and
    SKIP TRADEs, the exact same mechanism the existing daily-loss/
    capital-floor halts already use, not a new halt flag. Deliberately
    does NOT try to distinguish a losing streak from genuine strategy
    decay -- that stays `decay_supervisor`'s per-strategy job; this is a
    blunt, portfolio-wide response to being below the high-water-mark,
    whatever the cause.
  - `scheduler.py` computes both raw-equity-based (high-water-mark,
    drawdown tier -- fast, unlagged, for protection) and updates the
    persisted smoothed figure (for sizing only) once per run, right
    after virtual equity itself is computed. The drawdown multiplier and
    the smoothed/raw equity ratio combine into one `sizing_scale_factor`
    that multiplies into the SAME `risk_per_trade_override` mechanism
    `portfolio_allocator` already uses -- so it composes cleanly with
    per-strategy allocation weighting, and `risk.py`'s existing
    `min(risk_per_trade, override)` clamp still enforces the hard
    ceiling at the lowest level regardless of what these multipliers
    compute to. Neither ever forces an exit on an already-open position
    -- only new entries are affected, both `state.py` (new
    `smoothed_equity`/`high_water_mark` fields,
    `get_equity_tracking`/`set_equity_tracking`) persists across runs
    the same way `daily_risk_tracking` already does.
  - `manager_report.py` gained a `drawdown_summary` section (current
    tier, multiplier, high-water-mark, smoothed equity) for visibility;
    `cfd_cli.py manager-report` and `status` (the latter using real live
    equity, not the offline approximation) both print it.
  36 new tests (`tests/test_cfd_smoothed_equity.py` 9,
  `tests/test_cfd_drawdown_monitor.py` 10, `tests/test_cfd_state.py` +2,
  `tests/test_cfd_manager_report.py` +1, plus the drawdown-tier
  boundary/edge cases). Full suite: 347 tests passing. Live-smoke-tested
  against the real Deriv demo account after pushing, per the usual
  discipline for a scheduler.py change. Only gaps #10 (consolidated
  Qualification Gate), #11 (strategy pool diversity), and #3 (decision
  cadence, still deliberately last) remain from the Revision 3 gap
  analysis.

- **2026-09-20 — Revision 3 gap #10 ("Qualification Gate not
  consolidated") closed.** New module
  `trading/cfd/qualification_gate.py` (`qualify(name, version)`,
  read-only -- decides nothing, promotes nothing, never touches
  `CFD_ALLOW_LIVE_TRADING`): consolidates docs/VISION.md's 9-item
  Qualification Gate checklist into one report, checked ONLY against
  data this project actually persists in a structured, queryable
  form -- never an invented or assumed number:
  - `positive_expectancy_net_of_costs`, `passed_multiple_regimes`
    (`compute_performance()`'s own `by_regime` grouping -- distinct
    regime labels the strategy's own trade history spans, excluding
    `"unknown"`), and `drawdown_within_envelope` (same
    `MAX_DRAWDOWN_CAP`=-25% `research_lab.py`'s own candidate gate
    already uses) -- computed from live trade history once there are
    >= 20 of the strategy's own priced trades, falling back to paper
    trade history before that (paper is the only evidence available
    pre-`ACTIVE`).
  - `passed_out_of_sample`: scans the registry entry's own audit-trail
    `history` for a transition reason recording TEST/out-of-sample
    evidence (`research_lab.register_if_passed()`'s auto-written note
    already contains this for an auto-validated candidate; a
    grandfathered entry's note is checked the same way).
  - `strategy_version_frozen_during_qualification`: always PASS, with
    an explanation, not a bare claim -- structurally guaranteed by
    `strategy_registry.register()` refusing to overwrite an existing
    (name, version) at all, so there is nothing to verify at runtime.
  - `no_safety_rule_violations`: scans the registry history for any
    `"autonomous demotion"`-reasoned transition to `PAUSED` -- a
    strategy that ever decayed enough to trigger `decay_supervisor`
    fails this criterion, even if it was later resumed.
  - `live_demo_behavior_not_diverged`: `NOT_APPLICABLE` before
    `ACTIVE` (no live behavior exists yet to compare); once `ACTIVE`,
    splits the strategy's own paper trades at its `PAPER -> ACTIVE`
    promotion timestamp (from the registry history) and compares
    live-since-promotion win rate against pre-promotion paper win rate
    against a stated, unvalidated 25-point tolerance band.
  - Two of docs/VISION.md's nine listed criteria
    (`risk_controls_fired_correctly_under_test`,
    `no_duplicate_execution_incidents`) are reported `UNVERIFIABLE`,
    not silently passed or silently dropped: nothing in this codebase
    persists a structured log of a Portfolio Risk Governor rejection
    or a pending-entry adoption/foreign-position detection today --
    those events are only ever `logger.warning`/`logger.info` lines in
    the GitHub Actions run log, not a queryable record. Honest about
    the gap rather than claiming a check that isn't real; a genuinely
    complete gate still needs a structured incident log to replace
    this manual-review placeholder, tracked as follow-up work, not
    done here.
  - Overall `verdict` is `"ready_for_human_review"` only when every
    checkable criterion is `PASS` (an `INSUFFICIENT_DATA` or `FAIL` on
    any of them means `"not_yet"`) -- and even a full pass is still
    only ever evidence for a human to weigh, per docs/VISION.md's
    "Autonomy boundaries": this module has no path to enabling real
    money itself.
  - `cfd_cli.py qualify-strategy NAME VERSION` (wired into the "CFD
    Manual Command" GitHub Actions workflow's dispatch options)
    prints the full itemized report. Offline: no Deriv connection
    needed.
  11 new tests (`tests/test_cfd_qualification_gate.py`), full suite:
  358 tests passing. Live-smoke-tested against the real registry/trade
  logs on the live account (read-only; no scheduler.py change in this
  pass, so no live cron behavior changed) -- both `ema_crossover@v1`
  (currently `ACTIVE`, zero trades on record yet) and
  `donchian_breakout@v2` (`VALIDATED`) correctly report `"not_yet"`
  with honest `INSUFFICIENT_DATA`/`NOT_APPLICABLE` reasons, not a false
  pass. Only gaps #11 (strategy pool diversity) and #3 (decision
  cadence, still deliberately last) remain from the Revision 3 gap
  analysis.
- **2026-09-20 — Revision 3 gap #11 ("strategy pool is still 2 members,
  both trend-following") partially closed.** New module
  `trading/cfd/mean_reversion.py` (`MeanReversionStrategy`): fades price
  extremes back toward a Bollinger Band mean instead of following a
  breakout/crossover -- entry on a close outside the bands (long below
  the lower band, short above the upper), exit on reversion to the
  middle band or an ATR-based stop/target backstop (same protective
  shape `EmaCrossoverStrategy`/`DonchianBreakoutStrategy` already use, so
  entry logic is the one structural variable under test, not exit
  mechanics). A genuinely different structural bet from the existing
  pool, not a parameter retune -- picked specifically because
  `trading.cfd.regime`'s `"ranging"` classification has had zero
  registered strategies suited to it since the Strategy Selector was
  built, meaning every ranging period was a `NO TRADE` by omission, not
  design.
  - Registered into `strategy_registry.STRATEGY_CLASSES` and seeded as
    `mean_reversion@v1` (`CANDIDATE`, `suited_regimes=["ranging"]`,
    `scripts/seed_strategy_registry.py`) with the same disposition
    `donchian_breakout@v1` originally had: reasonable, sourced
    placeholder params (20/2.0 Bollinger Band textbook defaults; ATR
    stop/target mirroring the other two strategies' shape), explicitly
    UNVALIDATED, not yet run through a TRAIN/TEST grid search.
  - New `scripts/optimize_cfd_mean_reversion.py`, same TRAIN/TEST/
    overfit-safety discipline as `optimize_cfd_breakout.py` (imports its
    shared harness rather than copying it), wired into the "CFD Manual
    Command" GitHub Actions workflow as `optimize-mean-reversion`. Not
    yet run against live history -- `mean_reversion@v1` stays
    `CANDIDATE` with placeholder params until it is, same gate
    `donchian_breakout@v2` went through before promotion to `VALIDATED`.
  - 9 new tests (`tests/test_cfd_mean_reversion.py`, mirroring
    `test_cfd_breakout.py`'s pattern: entry/exit signal shape, stop/
    target computation, warmup-NaN handling, plus one `prepare()`
    coverage test for the indicator columns it adds), full suite: 367
    tests passing.
  - Still open from gap #11: `mean_reversion@v1` needs the actual grid
    search run and, if it clears TRAIN/TEST, promotion through
    `VALIDATED` before it can ever reach `ACTIVE` and actually trade;
    the pool is still single-timeframe (H1); no volatility- or
    session-based strategy variant exists yet. Tracked as remaining work,
    not silently closed.
- **2026-09-20 — Revision 3 gap #11 follow-up: `mean_reversion@v1`
  grid search run, found nothing, retired.** Ran
  `scripts/optimize_cfd_mean_reversion.py` against ~2 years of real H1
  forex/gold history (yfinance proxy feed, same instruments as every
  other grid search in this project) via the "CFD Manual Command"
  workflow. Result: baseline (default params) TRAIN cagr=-83.8%
  maxdd=-97.8% sharpe=-6.37 (1857 trades), TEST cagr=-81.2% maxdd=-76.8%
  sharpe=-6.03 (722 trades) -- catastrophic. All 81 grid combinations
  (`band_window` × `band_std` × `atr_stop_mult` × `atr_target_mult`)
  searched on TRAIN; **zero** cleared the qualification bar (CAGR > 0
  and drawdown within the -25% cap). Not a bug -- `test_cfd_mean_
  reversion.py`'s 9 unit tests still pass, the signal logic fires
  exactly as designed; this Bollinger-Band mean-reversion formulation
  simply has no usable edge on this data, probably because H1 forex/gold
  trends persistently enough that "faded" extremes keep extending rather
  than reverting, the opposite of what the strategy bets on.
  - `mean_reversion@v1` moved `CANDIDATE -> RETIRED` (`cfd_cli.py
    promote-strategy mean_reversion v1 RETIRED --reason "..."`) with the
    full TRAIN/TEST numbers recorded in its registry history, rather
    than left as a misleadingly-still-viable `CANDIDATE` nobody was
    going to grid-search again. Per docs/VISION.md's Research vs.
    Qualification environments: this is exactly what the Research
    environment is for -- a candidate that's free to be tried and found
    wanting, backed by a real, honestly-reported negative result, not
    silently dropped or force-fit into looking viable.
  - This is a negative result for one specific implementation, not proof
    no mean-reversion edge exists on these instruments -- a different
    indicator (RSI extremes, VWAP bands), a narrower instrument subset,
    or a different timeframe are all still untried. Gap #11 (strategy
    pool diversity) stays **open**: the "ranging" regime is back to zero
    suited `ACTIVE` or `CANDIDATE` strategy, exactly where it was before
    this attempt, just now with one ruled-out approach on record instead
    of an untested guess. Full suite: 372 tests passing (unaffected --
    the retirement is a registry state change, not a code change).
- **2026-09-20 — Revision 3 gap #3 ("only one open position per
  instrument, and only an hourly decision cadence") closed.** Two
  independent halves, both fixed:
  - **Decision cadence:** `.github/workflows/cfd-trading.yml`'s schedule
    changed from `cron: "5 * * * 1-5"` (roughly hourly) to
    `cron: "*/15 * * * 1-5"` (every 15 minutes). The candles evaluated
    are still H1 (`scheduler.py`'s `GRANULARITY_SECONDS` unchanged, still
    matching `EmaCrossoverStrategy`'s design) -- most 15-minute runs
    inside the same still-open hour see an unchanged candle and are a
    no-op re-check, not a new decision. What running more often than the
    candle itself buys: a signal exit or a ratcheting trailing stop is
    caught within ~15 minutes instead of waiting up to the rest of the
    hour, and a new entry into a slot that just freed up (or a slot the
    next change makes newly available) doesn't sit idle until the next
    hourly mark. Added a `concurrency: {group: cfd-trading,
    cancel-in-progress: false}` guard to the workflow at the same time --
    at 15-minute intervals a slow run could otherwise overlap the next
    scheduled one, and idempotency (`set_pending_entry`/
    `_reconcile_unknown_positions`) was only ever designed to recover ONE
    process crashing mid-run, never to arbitrate two processes racing to
    open the same order at once; `cancel-in-progress: false` queues the
    next run rather than killing one mid-order-submission.
  - **One position per instrument:** `trading.cfd.selector.
    select_for_entry()` gained an `exclude_tags` parameter -- strategy
    tags to skip even if otherwise regime-suited. `scheduler.py` now
    splits an instrument's open legs by which strategy opened them
    (`_legs_by_strategy`, new), manages each strategy-group to its own
    exit independently (same signal-exit/trailing-stop logic as before,
    just scoped per group instead of per instrument), and afterward
    still considers a NEW entry with `exclude_tags` set to every strategy
    already positioned on this instrument -- so the SAME strategy can
    never double up its own thesis on one instrument (still exactly the
    disguised-risk-split docs/VISION.md forbids, and still structurally
    prevented), but a genuinely different ACTIVE strategy suited to the
    same regime can open its own independent position there. Two
    different strategies' positions on the same instrument are two
    theses, not one; `trading.cfd.portfolio_risk`'s ceilings are keyed on
    instrument+side, never on strategy, so they already aggregated this
    correctly with no change needed there (confirmed by re-reading and
    correcting that module's docstring, which had claimed the broker
    layer enforced a single-position limit -- it only ever collapsed
    `open_positions()`'s display, `open_positions_list()`/
    `open_contract_ids()` already supported multiple contracts per
    instrument for the partial-close split). `CFD_MAX_OPEN_POSITIONS`
    now counts distinct (instrument, strategy) position slots
    (`total_open_slots`, computed once per run and mutated in place as
    groups close or new entries open, same pattern `open_risk_positions`
    already uses) instead of distinct instruments.
  - 8 new tests: 2 for `select_for_entry`'s `exclude_tags`
    (`tests/test_cfd_selector.py`), 3 for `_legs_by_strategy`
    (`tests/test_cfd_scheduler.py`). Full suite: 372 tests passing.
    `run_once()` itself has no direct unit test (needs a live/mocked
    broker, same as before this change) -- live-smoke-tested via the
    "CFD Manual Command" workflow against the real Deriv demo account
    instead; see below for the result.
  - Practical effect today: with only `ema_crossover@v1` currently
    `ACTIVE` (both `donchian_breakout@v2` and the now-retired
    `mean_reversion@v1` are not), there is only one ACTIVE strategy to
    ever occupy a slot, so no instrument will actually hold two
    simultaneous positions until a second strategy is promoted to
    `ACTIVE` -- but the cadence increase is live and effective
    immediately, and the architecture no longer has to be revisited when
    a second strategy does get promoted.
  - This was the last gap in the user's stated Revision 3 priority
    order. Gap #11 (strategy pool diversity) remains open on its own
    merits (see the entry above), not because it was skipped in order.
- **2026-09-20 — Autonomous weekly Research Lab (new capability, not a
  Revision 3 gap -- the user asked directly for a self-improvement loop
  that runs without waiting for a command).** New `scripts/
  research_cfd_strategies.py`: generalizes the existing single-strategy
  driver (`scripts/research_cfd_strategy.py`, `donchian_breakout` only)
  across every entry in `STRATEGY_SPECS` (currently `ema_crossover`,
  `donchian_breakout`, `mean_reversion`) -- fetches each configured
  instrument's history once, shares it across all three strategies' grid
  searches, and runs each through the same TRAIN filter -> `trading.cfd.
  research_lab`'s full Backtest/Out-of-Sample/Walk-Forward/Monte-Carlo
  gate already used elsewhere, auto-registering anything that clears
  every gate as a new version at `VALIDATED` -- never higher. Each
  strategy's pass is wrapped in try/except so one strategy's data or
  logic problem can't abort the others' passes in the same run --
  necessary now that this runs completely unattended.
  - New `.github/workflows/cfd-research.yml`: `cron: "0 6 * * 0"`
    (weekly, Sunday, before Monday's trading week) plus
    `workflow_dispatch` for an on-demand run; also wired into the "CFD
    Manual Command" workflow as `research-strategies` (plural,
    distinct from the existing singular `research-strategy`).
  - Hard boundary, unchanged and re-verified here: this can only ever
    reach `VALIDATED`. `trading.cfd.research_lab.register_if_passed()`
    (unmodified) has no path to `PAPER`/`ACTIVE`, and nothing in this new
    script calls `set_state` directly -- promotion stays a deliberate,
    reasoned `cfd_cli.py promote-strategy` command a human types, per
    docs/VISION.md's "What the AI Trading Manager chooses vs. what it may
    never touch." This is the "system improves itself" mechanism the
    vision describes -- generating and validating new candidates without
    a human remembering to ask -- explicitly NOT the "system trades
    itself into more risk on its own" pattern the vision forbids: risk
    ceilings, promotion, and real-money permission are untouched by it.
  - Also explicitly NOT code generation: a genuinely new strategy
    *structure* (the way `mean_reversion.py` departed from trend-
    following) still needs a person -- or Claude, asked -- to design and
    add to `STRATEGY_SPECS`; this loop only automates re-searching
    parameter space for structures that already exist there.
  - No new unit tests: this is an orchestration script over
    already-tested library code (`trading.cfd.research_lab`, covered by
    `tests/test_cfd_research_lab.py`, and the shared TRAIN/TEST/fetch
    helpers in `optimize_cfd_strategy.py`), the same untested-script
    precedent every other `optimize_cfd_*.py`/`research_cfd_strategy.py`
    driver already follows -- these need a live network connection and
    are validated by running them, not by a unit test suite. Full
    existing suite still 372 passing (no library code changed). Syntax/
    import-chain verified locally; live execution verified via workflow
    runs (see README's "Autonomous weekly research" section for what it
    reported once run).
- **2026-09-20 — Critical operational discovery: the `cfd-trading.yml`
  cron had never actually fired.** Found while trying to live-smoke-test
  `cfd-research.yml`: the GitHub API returned 404 dispatching it, which
  led to checking `main` -- 26 commits behind this branch, and its own
  copy of `cfd-trading.yml` had `schedule:` **commented out entirely**.
  GitHub Actions only ever reads a `schedule` trigger (and only ever
  discovers a `workflow_dispatch`-only workflow file as a distinct,
  API-dispatchable workflow) from the repo's *default* branch -- every
  run of `cfd-trading.yml` checked via the Actions API (`event` field)
  turned out to be `"workflow_dispatch"`, never `"schedule"`. So despite
  this project's own docs (README, this file, `cfd-trading.yml`'s own
  header comment) describing the cron as "enabled" since 2026-09-19,
  it had never once fired on its own -- every "live run" all session,
  and apparently every prior session too, was a manual dispatch, always
  explicitly targeting this branch via the API. This is the real reason
  `state/cfd_trades.jsonl` didn't exist yet despite the bot supposedly
  being live for over a day: nothing had ever actually run unattended.
  - Fix, in two parts. First (on this branch, no permission needed):
    pinned `ref: claude/ai-trading-manager-deriv-pmay2v` on the
    `actions/checkout` step of `cfd-trading.yml`, `cfd-research.yml`
    (both have `schedule:` triggers, which have no natural "ref" of
    their own to check out) and `cfd-manual-command.yml` (so a UI
    dispatch that forgets to switch the branch dropdown off the default
    still runs this branch's code) -- makes checkout deterministic
    regardless of which branch's copy of the workflow file GitHub used
    to fire the run. Second: flagged to the user that making the
    schedule actually fire required syncing these same 3 files onto
    `main` (nothing else -- no application code, since the checkout pin
    makes that unnecessary), and asked for explicit permission per the
    standing instruction never to push to a different branch without
    it. Permission given; pushed the 3 files to `main` directly via the
    GitHub API rather than a local `git push`. Confirmed after:
    `cfd-research.yml` now appears in the repo's workflow list
    (`state: active`), and `main`'s copy of `cfd-trading.yml` has
    `schedule:` genuinely uncommented.
  - Live-smoke-tested the fix by dispatching `cfd-research.yml` end to
    end (~33 minutes: 243 `ema_crossover` + 99 `donchian_breakout` + 81
    `mean_reversion` TRAIN combinations across 4 instruments' ~2 years
    of H1 history). Result: 0 combinations cleared even the cheap TRAIN
    gate for ANY of the three strategies this run -- including
    `donchian_breakout@v2`'s own already-`VALIDATED` parameters
    (`entry_window=80, exit_window=15, atr_stop_mult=3.5,
    atr_target_mult=6.0`, sitting at the edge of the searched grid),
    which previously cleared this same gate when originally validated.
    Not a bug in the new driver (stage-1 filter logic matches
    `optimize_cfd_breakout.py`'s own line for line) -- yfinance's
    rolling ~2-year window means the TRAIN/TEST split's date range has
    shifted forward since `donchian_breakout@v2` was originally found,
    so this is a genuine, fresh signal that its edge may not hold on
    the current window, not a re-confirmation of the old one. Nothing
    was registered or changed in the Strategy Registry as a result
    (correct: this only ever adds a new VALIDATED candidate on a pass,
    never retires or demotes an existing one on a research-only run) --
    surfaced here as a data point for a human reviewing
    `donchian_breakout@v2` before ever promoting it, not acted on
    automatically.
- **2026-09-20 — Third attempt at gap #11: `rsi_reversion` (built by
  GPT, reviewed and merged, then honestly ruled out too).** The user
  asked for a second AI to weigh in on the codebase; with no direct
  Claude<->GPT integration available, the collaboration ran through two
  GitHub artifacts instead: issue #2 (open questions for independent
  review -- promoting `donchian_breakout@v2` given its fresh negative
  signal, what structural approach to try next for "ranging," and a
  general "anything look off now that's built, not just designed"
  check) and PR #3 (a concrete build, to a spec this session wrote:
  `RsiReversionStrategy` -- fades RSI momentum exhaustion behind a
  strict ADX flat-market gate, structurally distinct from
  `mean_reversion@v1`'s Bollinger-band price-deviation fade, reusing
  only already-existing `rsi()`/`adx()`/`atr()` indicators).
  - PR #3 reviewed before merge, not merged on trust: diff read in
    full, branch checked out into an isolated worktree, full suite run
    there (383 passing, 372 existing + 11 new) before merge, and again
    on the merged result after. Code matched the spec and every
    existing convention (`Signal`/`Action` interface,
    `STRATEGY_CLASSES` registration, `optimize_cfd_*.py` TRAIN/TEST
    harness reuse, `STRATEGY_SPECS` integration for the autonomous
    weekly loop) -- merged via `merge_pull_request`, then this session
    added the two pieces outside the original spec:
    `rsi_reversion@v1` seeded as `CANDIDATE` (`suited_regimes=
    ["ranging"]`) via `seed_strategy_registry.py`, and
    `optimize-rsi-reversion` wired into the "CFD Manual Command"
    workflow, matching `optimize-mean-reversion`'s existing pattern.
  - Ran `optimize_cfd_rsi_reversion.py`'s real TRAIN/TEST grid search
    (243 combinations) via GitHub Actions. Result: only 1/108
    TRAIN-qualifying candidate, and that one (`rsi_oversold=30,
    rsi_overbought=75, adx_flat_threshold=15, atr_stop_mult=1.5,
    atr_target_mult=2.5`; TRAIN cagr=1.4% maxdd=-3.2%) failed
    out-of-sample: TEST cagr=-6.8% maxdd=-6.8% win_rate=14.3% (7
    trades) -- `[OVERFIT]`. Baseline itself was mild rather than
    catastrophic this time (TRAIN cagr=-1.1%, TEST cagr=+1.9% on only
    11/3 trades -- too thin to mean anything), unlike
    `mean_reversion@v1`'s wipeout, but still no combination held up
    out-of-sample. `rsi_reversion@v1` moved `CANDIDATE -> RETIRED`
    with the full numbers in its registry history, same honest-
    negative-result treatment as `mean_reversion@v1` -- not left as a
    misleadingly-still-viable `CANDIDATE`.
  - Gap #11 stays open: two structurally distinct approaches
    (Bollinger-band fade, RSI+ADX fade) are now ruled out on this
    data, not just one guess. Still untried: session/time-of-day-based
    approaches, a different timeframe entirely (every attempt so far
    is H1), or a genuinely different data source/instrument subset.
    Full suite: 383 tests passing throughout (the retirement itself is
    a registry state change, not a code change).
- **2026-09-20 — Event Blackout mechanism (new, not a Revision 3 gap --
  the start of the joint Claude/GPT news-integration design discussion
  in GitHub issues #4/#5).** GPT asked why this session had previously
  told the user it didn't recommend a news-searching trading system;
  answered in full on issue #4 (failure-mode analysis, a six-way
  comparison of possible news roles, a priority ranking, and a proposed
  measurable experiment). Both Claude's independent analysis and GPT's
  own stated hypothesis converged on the same answer without needing
  further back-and-forth: approach D (news as an event blackout / NO
  TRADE filter around scheduled high-impact releases) is the strongest
  starting point -- lowest infrastructure cost (a scheduled economic
  calendar, not freeform text needing NLP), only ever removes
  opportunity rather than adding a directional bet (same shape as
  `drawdown_monitor`'s severe tier), and has a working precedent
  already in this repo (the stock/Alpaca side's "Ongoing news
  monitoring" routine).
  - New `trading/cfd/event_blackout.py` (`EconomicEvent`,
    `in_blackout_window()`): the pure mechanism only -- a timestamp
    check against a supplied list of scheduled events, asymmetric
    before/after window widths, an impact-level floor. No data source,
    no network call, and **deliberately not wired into scheduler.py's
    live entry logic yet** -- doing so before a real TRAIN/TEST
    validation exists would contradict the exact discipline argued for
    in the issue #4 reply (a candidate proves itself on held-out data
    before touching a live decision, same as every strategy here,
    including the two retired this session). 12 new tests
    (`tests/test_cfd_event_blackout.py`). Full suite: 395 passing.
  - Still needed before the proposed backtest experiment can run: a
    concrete, reliably-timestamped economic calendar data source --
    posted back to GPT on issue #4 as a research question fitting its
    stated "market/news analyst" role in the collaboration model
    (issue #5), rather than guessed at here.
- **2026-09-20 — Fourth attempt at gap #11: `support_resistance` (proposed
  by GPT on issue #5, built this session) -- found and fixed a genuine
  strategy bug, not a validated result yet.** `trading/cfd/
  support_resistance.py` (`SupportResistanceReversionStrategy`) is the
  first "ranging" attempt with a structurally different data
  representation, not just a different formula over closes: confirmed
  swing-high/swing-low price structure (strict-inequality left/right
  rolling windows, `shift()`-confirmed by `pivot_window` bars so a pivot
  is never used before it could genuinely have been known -- caught and
  fixed pre-commit by a test that initially failed against an earlier,
  equality-based pivot check that false-triggered on flat/tied price
  runs). 12 unit tests, `optimize_cfd_support_resistance.py` (81
  combinations), `support_resistance@v1` seeded `CANDIDATE`
  (`suited_regimes=["ranging"]`). Committed as f5ebcb2; full suite 407
  passing.
  - The first live grid search (GitHub Actions run 35511985083) came
    back with impossible numbers: best "robust" candidate
    `{pivot_window: 8, touch_threshold_pct: 0.0005, atr_stop_mult: 1.0,
    atr_target_mult: 1.5}` showed `TRAIN cagr=76,253,302.1%` / `TEST
    cagr=11,440,014.7%`, with 66/81 combinations "qualifying" and every
    top-10 TRAIN candidate showing similarly astronomical TEST numbers
    (5,000-6,400 trades on TRAIN alone, where every other CFD strategy
    here produces dozens to low hundreds on the same data). No genuine
    trading edge produces multi-million-percent CAGR -- treated as a
    bug to find, never as a candidate to register, exactly the same
    standard applied to `mean_reversion@v1`/`rsi_reversion@v1`'s honest
    negative results, just on a number that was too good instead of too
    bad.
  - Root cause: `signal_for_row()`'s entry check had no lower bound --
    `row["low"] <= support * (1 + touch_threshold_pct)` is equally true
    for a low sitting exactly at a genuine touch AND for a low far
    *below* an already-broken support (support only updates on a fresh
    confirmed pivot, which can lag well behind a real breakdown in a
    trending move). While flat, this fired a `BUY` signal on every
    single bar price stayed below a stale level, not once on an actual
    touch -- the pathological trade count above. Percentage-of-equity
    position sizing (`CfdRiskManager.stake_and_limits`, sizing every
    trade off current equity) then compounded that inflated trade count
    into the impossible CAGR figures; the backtest engine and risk
    sizing themselves are correct and were ruled out first by reading
    `backtest.py`/`risk.py` directly -- the defect is entirely in the
    strategy's own entry condition.
  - Fix: both entry checks now require the low/high to land *inside* a
    two-sided tolerance band around support/resistance
    (`support * (1 - touch_threshold_pct) <= row["low"] <= support * (1
    + touch_threshold_pct)`, symmetric for resistance), not merely
    at-or-beyond one side of it. All 12 existing unit tests pass
    unchanged (none exercised a "far below" case); two new regression
    tests added (`test_flat_low_far_below_stale_support_does_not_
    open_long`, `test_flat_high_far_above_stale_resistance_does_not_
    open_short`) covering exactly the scenario that produced the bad
    numbers. Full suite: 409 passing.
  - Re-ran the grid search against the fixed logic (GitHub Actions run
    35512685177). Numbers are sane now -- 2,714 TRAIN / 1,172 TEST
    trades, in line with the other CFD strategies' counts on this data,
    confirming the fix worked -- but the honest result is a clear
    failure: baseline `TRAIN cagr=-91.8% maxdd=-99.5% win_rate=48.1%`,
    `TEST cagr=-94.5% maxdd=-91.4% win_rate=45.4%` (near account
    wipeout on both splits), and **0/81** parameter combinations cleared
    even the cheap TRAIN gate (min trades, CAGR>0, drawdown within
    -25%). `support_resistance@v1` moved `CANDIDATE -> RETIRED` (`cfd_
    cli.py promote-strategy support_resistance v1 RETIRED --reason
    "..."`) with the full numbers in its registry history -- same
    honest-negative-result treatment as `mean_reversion@v1` and
    `rsi_reversion@v1`, not left as a misleadingly-still-viable
    `CANDIDATE` just because the bug that inflated its first numbers is
    fixed. Full suite: 409 passing throughout (the retirement itself is
    a registry state change, not a code change).
  - Three structurally distinct approaches (Bollinger-band fade,
    RSI+ADX fade, swing-structure reversion) are now ruled out on this
    data. Gap #11 stays open -- still untried: a session/time-of-day
    approach, a different timeframe (every attempt so far is H1), or a
    genuinely different data source/instrument subset.
- **2026-09-20 — Ranging-regime diagnostic (new, not a strategy) --
  checking the shared assumption behind all three retired attempts
  before building a fourth.** Posted the three retirements back to
  issue #5; GPT's read was that three structurally distinct fades
  failing is itself evidence worth investigating before assuming the
  next fade will do better -- asked for a diagnostic on `trading.cfd.
  regime`'s `RANGING` label itself: composition by instrument/session/
  volatility, episode persistence and transitions, and forward-return/
  excursion behavior after a `RANGING` episode starts, with no strategy
  logic applied, to check whether the label is mixing genuinely quiet
  consolidation with pre-breakout compression or noisy chop -- three
  different structures a single fade has no business treating
  identically.
  - Added `classify_regime_series()`/`classify_volatility_series()` to
    `trading/cfd/regime.py` -- vectorized siblings of the existing,
    live last-bar-only `classify_regime()`/`classify_volatility()`,
    same thresholds, evaluated at every bar instead of just "now."
    Neither is used by any live decision path; both exist purely for
    this kind of per-bar research. 4 new tests confirm each series
    agrees with its live counterpart at the last bar (not a second,
    independent definition of the same thresholds to drift out of
    sync).
  - New `scripts/diagnose_cfd_regime.py`: not a strategy or a backtest
    -- fits no parameters, reports no CAGR. Fetches full yfinance
    history per instrument (no TRAIN/TEST split -- there's nothing
    here that could overfit, so splitting would only throw away
    statistical power on a purely descriptive question), then reports
    regime composition (overall and by rough UTC-hour session bucket),
    episode length distribution and what a `RANGING` episode
    transitions into when it ends, and forward return/max-favorable/
    max-adverse-excursion over 5/10/20-bar horizons split by the ATR%
    volatility bucket at the episode's start. 10 new tests for the
    script's pure helper functions (episode-splitting, percentile/
    percentage formatting, session-bucket boundaries). Wired into
    `cfd-manual-command.yml` as `diagnose-regime`. Full suite: 423
    passing.
  - Ran live (GitHub Actions run 35515244461) across all 4 instruments,
    full available yfinance history (~13,700-17,240 H1 bars each).
    Results, read together:
    - **Composition**: `RANGING` is 44.6-55.3% of bars per instrument,
      `TRENDING` 44.6-54.0%, `UNSTABLE` nearly absent (0-0.3%). Fairly
      balanced, and **session doesn't meaningfully change it** --
      Asian/London/NY/Late all read within a few points of each
      instrument's overall ranging %, no session stands out as
      structurally different.
    - **Persistence**: `RANGING` episodes last a median 18-25 H1 bars
      (18-25 hours), the same order of magnitude as `TRENDING`
      episodes (18-21 bars median) -- not unusually short or long.
    - **Transitions**: a `RANGING` episode ends into `TRENDING`
      99.6-100% of the time across every instrument (`UNSTABLE` is too
      rare to be a meaningful transition target) -- not informative on
      its own given how rare `UNSTABLE` already is.
    - **Forward behavior (the key result)**: forward return after a
      `RANGING` episode starts is close to zero at every horizon
      (5/10/20 bars) and every instrument -- mostly between -0.2% and
      +0.25%, no consistent sign. MFE/MAE are roughly **symmetric**
      (e.g. gold, `normal` bucket, 20 bars: MFE +0.80%/MAE -0.71%) --
      consistent with genuine two-sided price action, not one-sided
      breakout drift.
    - **The volatility-bucket split didn't have enough data to be
      conclusive**: 85-97% of `RANGING` episode starts read as
      `normal` volatility under `classify_volatility_series()`'s
      existing 0.6x/1.5x-of-median thresholds -- the `low` bucket had
      only 1-3 episodes per instrument, `high` only 9-12. Far too thin
      to confirm or rule out "quiet consolidation vs. pre-breakout
      compression vs. noisy chop" at this bucketing resolution; a
      finer-grained (e.g. percentile-based) volatility split or more
      history would be needed to actually test that specific
      hypothesis.
    - **Reading**: no strong evidence the `RANGING` label is mixing
      multiple incompatible structures -- it looks like one
      reasonably coherent, near-zero-net-drift, symmetric-excursion
      population at the current bucketing resolution. Combined with
      MFE typically only a few tenths of a percent over 20 bars (H1,
      so ~20 hours) -- thinner than this project's own modeled spread/
      financing costs in most cases -- the more likely explanation for
      all three retired fades' failure is **transaction costs eating a
      real but thin edge**, not "wrong regime substructure." Posted in
      full to GPT on issue #5 for the joint read, since this changes
      what's worth building next (parameter/cost-model rework of the
      existing fade shape, vs. a structurally new
      volatility-expansion/breakout-transition candidate) more than
      the diagnostic alone can settle.

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

# Architecture Audit vs. Master Vision

Audit date: 2026-09-19. Compares the current codebase (see `docs/VISION.md`
for the target) against what actually exists on
`claude/ai-trading-manager-deriv-pmay2v`. This audit is read-only — no
trading logic was changed as part of it.

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
Market Regime Engine       -> MISSING for CFD (stock-only regime.py, wrong asset class)
AI Trading Manager         -> MISSING entirely (no decision-making layer above "run the one configured strategy")
Strategy Selector          -> MISSING (strategy is a fixed config choice, not a runtime decision)
BUY/SELL/NO TRADE          -> PARTIAL (each strategy emits BUY/SELL/HOLD; "NO TRADE" is not a first-class strategy/decision, just an absence of signal)
Risk Governor              -> PARTIAL (CfdRiskManager exists and is structurally right, but (a) sized off raw broker balance not virtual equity, (b) nothing stops the AI Trading Manager layer from bypassing it, because that layer doesn't exist yet)
Execution Engine           -> EXISTS (scheduler.py + broker.py)
Deriv                      -> EXISTS
Trade Database             -> MISSING (README says so explicitly: "this project doesn't yet keep its own trade-by-trade P&L log")
Performance Engine         -> MINIMAL (compute_cfd_metrics: total return, CAGR, Sharpe, max DD, win rate, trade count only -- missing expectancy, profit factor, avg win/loss, R multiple, Sortino, Calmar, losing streak, by-strategy/regime/session breakdowns, long-vs-short, exposure)
Failure Analysis            -> MISSING entirely
Research / Improvement Lab -> MISSING entirely (no automatic candidate generation; new strategies are hand-written)
Validation                  -> PARTIAL (TRAIN/TEST split with an overfit check exists; no walk-forward, no Monte Carlo/stress test, no paper-trading promotion gate)
Strategy Registry            -> MISSING entirely (no versioning, no lifecycle states -- strategies are just importable classes)
```

## Other vision requirements not yet met

- **Strategy pool breadth**: only Trend/Momentum (EMA crossover) and
  Breakout (unvalidated) exist for CFD. Missing: Mean Reversion, Volatility
  Expansion, Pullback, Multi-Timeframe, and NO TRADE as an explicit,
  trackable strategy rather than an implicit default.
- **Operating modes** (Defensive/Normal/Aggressive/Recovery/Paused): only
  `paused` exists today (`cfd_bot_state.json`). No mode concept, no
  mode-dependent tactics within the same hard risk ceiling.
- **Hard prohibitions**: no martingale/revenge-trading logic exists in the
  current code (good — nothing to remove), but there's also no explicit
  guard *preventing* a future change from introducing risk-scales-with-loss
  behavior. The stock system's `RiskManager.ladder` does the *opposite*
  (scales risk with *cushion above floor*, i.e. more risk only from house
  money) — a fine pattern, but worth calling out so it's never confused
  with "increase risk after a loss."
- **Minimum order size vs. $100 accounts**: `stake_and_limits()` currently
  has no explicit "skip if Deriv's minimum stake/multiplier would force
  risk above the configured limit" check — it computes a stake and clamps
  it to `min(..., self.equity)`, but doesn't compare against Deriv's actual
  minimum stake and bail out. Needs an explicit SKIP TRADE path per the
  vision.

## Decisions needed before writing more code

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

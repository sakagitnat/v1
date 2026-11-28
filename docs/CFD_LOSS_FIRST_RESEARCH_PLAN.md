# CFD research loss-first audit and notebook workflow (2026-11-02)

## Safety and source of truth
- Source: `gpt/autonomous-demo-runner`; do not modify runtime state manually.
- Keep `CFD_ALLOW_LIVE_TRADING=false`; no real-money trades.
- Preserve ACTIVE_DEMO, PAPER, SHADOW attribution; never aggregate as if equally executable.
- Notebook is an optional read-only analysis workstation; GitHub Actions continues running without it.

## Phase 1 — Data integrity before optimization
1. Reconcile every closed-trade event against account ledger and current `virtual_accounts`. Flag missing IDs, duplicates, timezone mismatches and the previously reported 238-row PAPER discrepancy; do not silently rewrite history.
2. Verify broker DEMO fills vs simulated PAPER fills; track entry, exit, commissions/spread/slippage, timeframe, regime, strategy version and instrument.
3. Compare per-account starting equity + realized P&L = ending realized equity; calculate open/unrealized separately and label unavailable data.
4. Record scheduler heartbeat age, workflow trigger (schedule vs dispatch), failed jobs, pending EURUSD intent, quota errors and other incidents.

## Phase 2 — Loss-first metrics
For every virtual account and for portfolio by tier:
- gross_profit = sum(max(realized_pnl, 0)); gross_loss = sum(min(realized_pnl, 0)); net = gross_profit + gross_loss
- win/loss/breakeven counts, average win, average loss, profit factor (undefined when no losses), expectancy, median P&L, longest losing streak.
- starting/current realized equity, open position count, unrealized (only if verified), peak-to-trough maximum drawdown from ordered equity series (not merely drawdown from initial capital).
- execution cost and stop/target/timeout exit attribution, regime and session.
- correlation and same-thesis concentration across accounts; account ruin/failure causes.

## Phase 3 — Hypotheses (not claims)
A. Compare M5 mean reversion in ranging vs trending, with matched exposure and out-of-sample forward observations.
B. Investigate H1 breakout losses by stop distance, regime misclassification, volatility and holding period.
C. Test XAUUSD and USDJPY concurrent thesis exposure limits on SHADOW before any promotion.
D. Track H4, H1, M15, M5, M1 and tick/seconds separately; do not infer profitability from empty sample buckets.
E. Test exit alternatives and sizing changes in isolated PAPER/SHADOW only; keep approved high-risk experiments isolated, preserve ruin evidence.

## Phase 4 — Acceptance gates
- Reconciliation: zero unexplained discrepancies for a selected forward window; historical discrepancies explicitly tagged.
- Every closed trade attributable to one account, strategy version, timeframe, instrument, regime and execution tier.
- Reports show gross losses prominently, not just net profit; all 49 accounts listed including inactive accounts.
- No forward-data leakage, no retrospective parameter selection presented as forward evidence.
- No promotion or risk increase without pre-registered test, sufficient forward sample, costs and drawdown limits.
- Daily 23:00 Asia/Bangkok report: per-account start/end, realized, gross gains/losses, closed W/L, max DD, open/unrealized, ruins; tier-separated and combined comparisons.

## Notebook setup (Windows, read-only)
1. Install Git and Python 3.11+.
2. `git clone https://github.com/sakagitnat/v1.git`
3. `cd v1 && git switch gpt/autonomous-demo-runner`
4. `py -m venv .venv`
5. `.venv\\Scripts\\activate`
6. `python -m pip install -r requirements.txt`
7. Analyze copies of `state/` locally. Do not commit secrets, modify live state or run trading scripts from the notebook.
8. GitHub Actions remains the autonomous runner; no need to leave the notebook powered on.

## Next implementation tasks
- Build read-only loss-first reporter with deterministic tests for empty trades, all-wins, all-losses, open positions and missing prices.
- Add ledger integrity report and explicit historical discrepancy register.
- Add daily report artifact with per-account table and strategy/timeframe/regime/instrument breakdown.
- Review results and tests in PR before modifying runtime trading logic.

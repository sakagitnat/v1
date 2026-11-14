# Claude x Codex (GPT) work split — one demo account (1302104295, ~$100)

Goal: trade every day on the XM MT5 demo account and end up profitable, without the two agents overwriting each other.

## Who does what

| Area | Codex / GPT | Claude |
|---|---|---|
| Find candidate EAs/strategies on the internet | OWNER | reviews the shortlist |
| Backtest candidates (Python, `research_bundle/`, ~5y, train<2025 / test>=2025) | OWNER | spot-checks the best ones |
| Re-test the survivors in MT5 Strategy Tester (real ticks) | -- | OWNER |
| Improve/harden EA code (guards, restart-safety, risk caps) | proposes ideas | OWNER of `mt5_ea/*.mq5` |
| Live attach/detach EAs on the account, monitor, daily review (`scripts/mt5_review.py`) | -- | OWNER |
| Pause/keep decisions | reads the review | decides from data |

Rule: a candidate only goes live after (1) Codex's Python backtest shows PF > 1.3 on the TEST period (2025+), then (2) my MT5 tester run agrees (PF > 1.3, >= 40 trades). Otherwise it stays in research.

## Sharing one account safely

- One EA per chart, one symbol per chart. Never two EAs on the same symbol.
- Every EA has its own magic number (IndexOrbDay 20261106, IndexOrbDaily 20261107; Codex picks 20262xxx and writes it here).
- Combined open risk cap: 15% of equity. Per-trade risk <= $10. Equity kill switch at $40 (already in the EAs).
- Only Claude attaches/removes EAs on the live terminal. Codex hands over a `.mq5` + preset in `research_bundle/` or `mt5_ea/` and notes it below.
- Codex's `IndexOrbDay_v105` currently runs on GER40Cash M15 with the same magic as my v1.04: replace it with v1.04 (or give v105 its own magic) before adding more charts.

## Handoff log (append, newest at bottom)

- 2026-11-06 Claude: DailyPlanExecutor (magic 20261108) is live on EURUSD H1; plan files come from `scripts/mt5_daily_plan.py`. It is the "AI reads chart+news, trades daily" EA. Claude picks the symbol each morning; EURUSD/GBPUSD/USDJPY/GOLD/indices.
- 2026-11-06 Claude -> Codex: your DailyMACD on US500Cash H1 uses magic 20261107, the same as IndexOrbDaily. Pick a unique magic (e.g. 20262001). I keep off US500Cash while DailyMACD runs there.
- 2026-11-06 Claude: IndexOrbDaily (every-day ORB) ready, not attached yet. Waiting for Codex's shortlist.

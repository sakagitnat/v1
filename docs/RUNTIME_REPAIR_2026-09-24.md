# Deriv DEMO runtime repair — 2026-09-24

## Verified starting evidence
- Last pre-change runtime: 35955684856, completed 04:27:59 UTC.
- Four quota ledgers: 17 closed trades, realized total -$0.91; these were execution_v1 probes of roughly 9 seconds, not timeframe-strategy evidence.
- A legacy experimental USDJPY contract (13803503519) remained tracked since September 21.
- Scheduler launch gaps exceeded three hours despite a fifteen-minute cron.

## Changes
- Bounded 180-minute service checks quota exits/entries approximately every minute and runs the research scheduler every fifth cycle. Broker calls can lengthen a cycle. Every cycle commits state and heartbeat; any ambiguous broker result or checkpoint failure stops the service. Artifact/final persistence stays enabled.
- Watchdog dispatches the actual main trading workflow, only if stale and no active/pending trading run. Removed ineffective GITHUB_TOKEN push-to-kick and unsolicited issue-comment recovery.
- Legacy experimental broker-managed DEMO probes get maximum holding times (TICK/M1/M5: 30m; M15: 1h; H1: 4h; other legacy probes: 6h). Persist close intent first; verified contract settlement still owns P&L and metadata removal. Quota and unknown/manual positions are excluded.
- Quota timeframe_v2 uses completed M30/H1/H4/D1 candles, persists positions across cycles, and requests close two minutes before the UTC quota window ends, or accounts for earlier broker exits. No fixed eight-second round trips. One position per quota ledger, no duplicate entry in completed windows. The signal is an experimental two-candle directional baseline, NOT a selected/qualified profitable strategy.
- Legacy execution_v1 results stay intact and must be analyzed separately from timeframe_v2, by account/strategy/timeframe/instrument/regime. Logical account balances remain cumulative; do not imply fresh $100 balances for v2.
- Missing evaluation windows are explicitly logged as EVALUATION_GAP, not fabricated as missed trades on markets whose availability was never observed.
- Legacy micro/high-risk/starter/rebase/manual state writers now share cfd-trading concurrency with the service. Position slots are five for the service to accommodate four quota ledgers; dollar risk checks, daily loss caps and the $1.50 research-risk limit remain.

## Validation
Local test suite: 514 tests pass (workflow tests updated for dispatch-only watchdog and new service; added deadline, broker exit, no-duplicate recovery, failure checkpoint and overdue-probe coverage).

## Limits / handoff to Claude
This file is repository handoff, not proof Claude has read it. DEMO only. GitHub hosted schedules can delay/drop launches; a bounded loop reduces gaps but does not guarantee 24/7. For that guarantee use an always-on worker and durable transactional order journal. Git state persists per cycle, not at the exact broker transaction instant; process loss between an order and checkpoint remains a recovery risk. A persistent worker needs available hosting access, not imaginary credentials. No profitability, full slippage/spread attribution, or best-strategy selection claim. Daily/weekend market closures and broker stops can affect quota outcomes.

Official platform references:
- https://docs.github.com/en/actions/how-tos/troubleshoot-workflows
- https://docs.github.com/en/enterprise-cloud@latest/actions/concepts/security/github_token

## Deployment verification
- PR #18 merged into runtime: b5919c5228fc7a89219e9b790613cdb816093cdf.
- Main workflow deployment: c26a01a1289013c33beeca9866f1cc5cf6bbb8ff.
- Live DEMO service run: https://github.com/sakagitnat/v1/actions/runs/35957074348 (still in progress as intended for the bounded service).
- GitHub CI run 35957073305 completed successfully.
- Two remote checkpoints verified at 04:47:07 and 04:47:54 UTC (832bf6b and 4a683f8).
- Legacy contract 13803503519 settled with verified P&L +$0.52, exit reason legacy_demo_probe_max_holding_time. starter_m5_probe ledger is $100.52. Trade-log equity_after on this legacy reconciliation is master equity, not logical account equity; use the account ledger for account balances.
- New contract 14189898999 opened using M30 completed candles under quota_30m_forward@timeframe_v2 at 04:46:55 UTC and remained open across the two checkpoints. Scheduled deadline 04:58 UTC. Closing this contract at its deadline has not yet been observed at handoff.

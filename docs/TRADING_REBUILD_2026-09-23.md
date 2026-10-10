# Trading rebuild — accepted requirements and implementation handoff

Approved by the user in the 2026-09-23 conversation. This document supersedes conflicting older VISION rules for quota RESEARCH accounts only. Production-like simulation remains signal-driven. DEMO/PAPER ONLY; real-money deployment is not authorized.

## Objective
An autonomous, evidence-driven multi-strategy manager that the user does not have to trade manually. Profit after costs is the objective, not a promised outcome. System reliability and strategy profitability have separate acceptance gates.

## Account model
All NEW experiment ledgers begin at USD 100. Preserve historical accounts, trades, failed versions and bankrupt experiments. Never overwrite old balances or reset losing history. Name broker accounts separately from virtual subaccounts. Existing Deriv code uses a shared demo account and virtual ledgers; those are NOT independently funded broker accounts.

Three roles:
1. SYSTEM_TEST: controlled opening/closing and recovery tests; exclude from strategy performance.
2. RESEARCH: compare strategies, instruments, regimes and horizons, including forced-quota variants. Identify each forced trade explicitly; never combine with signal-driven evidence.
3. REALISTIC_SIM: qualified strategy versions only; may skip when criteria fail, recording why. No forced entry to fill quota.

Research horizons: 1800, 3600, 14400, 86400 seconds; optional weekly horizon 604800. Each research account targets at least one complete OPEN-to-CLOSED lifecycle inside each eligible horizon window. Proposed implementation convention: UTC-aligned non-overlapping windows. A missed window is an explicit breach, never backfilled/fabricated. Broker minimum holding time, market closure, unavailable prices, risk limits and rejected orders remain real constraints: record the blocker, do not bypass it to claim compliance. Distinguish signal candle interval, holding deadline and quota window. Longer horizon simulations may hold across days under their own documented rules.

Run monitoring continuously, trade only eligible open instruments. Never silently substitute instruments when a market closes. Any weekend/24-hour instrument requires its own product constraints and strategy evidence.

## Required architecture
- One authorized execution writer per broker account across ALL runner processes and workflows.
- Durable transactional state (orders, fills, reservations, account ledger, decisions, incidents). Git holds code, configuration and reproducible research reports; git commit/rebase is not the sole order-state durability mechanism.
- Acquire account ownership before reconciliation or order submission; prevent an expired owner from submitting after takeover.
- Persist intent before submit. Ambiguous buy/sell results enter reconciliation; no blind retry.
- Reconcile by broker contract/order identifiers and actual contract history. Aggregate balance changes cannot safely attribute P&L to individual trades when multiple positions, fees or cash movements occur.
- Track balance, reserved capital, realized P&L, floating P&L and net liquidation equity separately.
- Restart recovers old positions before considering new entries. Unknown broker exposure blocks new exposure and is reported.
- Risk limits at virtual-account and shared-broker levels; include correlated exposure. Explicit configurable per-trade, total exposure, daily loss and drawdown limits. High-risk trials remain isolated, not an automatic loss-recovery escalation.
- Live-money authorization remains disabled. Product identity matters: the current adapter uses Deriv Multipliers, not MT5 CFD orders. Do not reuse a CFD margin/fee model without verifying product semantics.
- AI analyzes evidence and proposes versioned changes; deterministic code executes approved rules. AI unavailability must not prevent managing existing positions.
- Strategy changes need hypothesis, baseline, out-of-sample evaluation, versioned results, promotion/demotion criteria and rollback. No automatic promotion based on a few wins.
- Include fees, spread, slippage, minimum trade sizes, accepted multiplier values, market calendar and financing where applicable; document simulation limitations rather than claiming exact live equivalence.
- Do not leak broker tokens, OTP URLs or raw sensitive responses in logs.

## Data and reports
Each decision/trade records account/experiment ID, strategy version, instrument, product, signal timeframe, holding deadline, quota window, regime, timestamp, data freshness, entry/exit reasons, forced-vs-signal label, size, costs, broker IDs, execution outcome and realized/floating P&L.
Every evaluation produces TRADE, NO_SIGNAL, MARKET_CLOSED, RISK_BLOCKED, DATA_STALE, ORDER_REJECTED, RECONCILIATION_REQUIRED or SYSTEM_ERROR; silence is not a healthy no-trade.
Daily report: system heartbeat and incidents separately from results; completed/missed windows; balances and equity; open/closed trades; net P&L; drawdown; uncertainty and evidence by account/strategy/timeframe/instrument/regime. Do not explain each loss with an invented cause.
Cashflow/contract evidence wins over inferred P&L. Missing information stays explicitly unknown.

## Acceptance gates
A. Correct execution: complete one demo lifecycle; no duplicate order after timeout/restart; recover open position; reconcile actual close; verify durable journal and balances.
B. Operational stability: monitor continuously; stale data and disconnect fault injection; safe ownership takeover; missed-window alerts; failure persists across process termination.
C. Multi-horizon research: exercise all required windows with independent ledgers and visible quota results. Real-time daily/weekly evidence requires elapsed time; a simulated clock test cannot be presented as live evidence.
D. Strategy qualification: net performance, drawdown, sample size, elapsed market regimes, frozen out-of-sample/forward results and comparison to unchanged baseline. Record unsuccessful candidates.
E. Controlled migration: inventory and reconcile legacy writers/positions; archive old state; stop old writer; switch one owner; verify; rollback if needed. Do not delete history or interrupt an unresolved open position.

## Verified audit on 2026-09-23
- main inspected at c54754e627f4abe16761fa6bed1b44a273893df0.
- Active runtime branch inspected at d4afd604212ca8fcacc28a5d68ac4b5fa31b2b31 (gpt/autonomous-demo-runner).
- main CFD Trading and watchdog check out the runtime branch, not main code.
- Run https://github.com/sakagitnat/v1/actions/runs/35873570386 failed in broker.connect POST /accounts/{id}/otp with ConnectionResetError. Dependency installation succeeded. This is a verified cause for this run, not proof of every historical failure.
- The broker REST bootstrap had no explicit timeout or bounded retry.
- Runtime state heartbeat records failure at 2026-09-23T14:22:01Z. A prior success heartbeat is not proof a trade occurred.
- Recent GPT Handoff CI runs had conclusion action_required. Do not claim CI passed.
- Existing virtual-account definitions include 30m/hourly quota ledgers but are not evidence that the new four-horizon specification is implemented.
- Scheduler reconciliation currently infers a single disappeared contract's P&L from account balance delta. This needs replacement with contract-level evidence before reliable multi-account attribution.
- GitHub Actions workflows start/stop jobs and save state by git push. This architecture does not establish continuously running execution with guaranteed horizon deadlines.

## Implemented in this change
Connection bootstrap:
- Run blocking REST calls in asyncio.to_thread.
- GET accounts / POST OTP have 5s connect and 15s read timeouts.
- At most 3 attempts on connection/timeout errors with 1s/2s delays.
- OTP retry obtains a new credential; never retries a trade.
- HTTP errors/redirects fail immediately without printing response bodies.
- Explicit WebSocket handshake/close timeouts.
- Existing demo account selection remains intact.

Validation: 9 offline failure-injection tests pass (OTP reset recovery; bounded timeout; 302/401/403/429/500 fail-fast; no fallback to real account; no retransmission of ambiguous buy). This does NOT validate actual Deriv connectivity or full system operation.

## Claude handoff / next implementation work
Use this accepted specification, not the older quota-free vision for research accounts.
Review the bounded-bootstrap fix and tests. Establish a continuously running host and durable journal before expanding trading. Inventory all writers and broker open positions before switching. Replace aggregate-P&L attribution, implement four-horizon research and realistic-simulation accounting, then validate gates A–E.
No direct Claude session communication has been verified. This repository document and PR are the durable handoff; receipt by Claude is not assumed.


# Dual-broker CFD research architecture

Status: proposal; do not change running execution without reviewed tests.

## Non-negotiable
- Keep Deriv GitHub Actions DEMO service, scheduler, existing state, virtual ledgers and strategy registry running unchanged.
- Add XM MT5 as a separate Windows-hosted DEMO-only adapter. Default to read-only, and refuse to send orders unless terminal account is verified demo and explicit demo-order flag is enabled.
- No real-money order execution. Never store XM login passwords in GitHub, logs or chat.
- Do not transfer Deriv positions, balances, order IDs, or historical fills to XM.
- Research signals can be reused, but require broker-specific symbol mapping, contract size, pip/tick value, margin, spread, execution, timezone and cost tests.

## Shared research schema
Record: broker, account, execution_tier, symbol, strategy/version, signal timestamp UTC, timeframe, regime, side, quantity/lot, entry/exit, stop/target, spread, slippage, commission, swap, realized P&L, open/unrealized, close reason, correlation group, order/fill IDs, source and quality flags.
Separate broker ledgers and reports, then provide cross-broker comparison only for matched instruments, sessions, and normalized risk.

## Implementation phases
1. Read-only XM MT5 health probe: terminal present, initialized, account_info, trade_allowed, server, demo-vs-real classification, symbols, ticks, bar history, no order_send.
2. Historical data validation and strategy signal parity against Deriv research, with no look-ahead.
3. Demo order adapter with explicit opt-in, hard account-type guard, lot rounding, margin, SL/TP and duplicate order protection; test on XM demo only.
4. Unified read-only dashboard with broker tabs and loss-first metrics: gross gains, gross losses, net, W/L, profit factor, maximum drawdown, open risk, incident flags, provenance.
5. Parallel forward study; preserve Deriv as independent control and evaluate broker-specific outcomes before any risk changes.

## Windows operation
- Python MetaTrader5 integration requires locally installed MT5 terminal and signed-in XM demo.
- If notebook sleeps or MT5 closes, local XM execution pauses. GitHub-hosted Deriv is unaffected.
- Avoid automated broker login and avoid exporting credentials.

## Acceptance
- Deriv workflow and state unchanged by XM changes.
- XM default startup sends zero orders.
- Real XM account is refused by execution adapter.
- Data source and broker are visible on every trade and chart.
- Both brokers report losses as prominently as gains.

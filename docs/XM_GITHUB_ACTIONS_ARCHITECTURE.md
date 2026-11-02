# XM MT5 execution via GitHub Actions — architecture decision

GitHub Actions can orchestrate XM MT5 research and jobs, but a broker MT5 terminal is required for the usual MetaTrader5 Python execution route. Existing GitHub-hosted Ubuntu Deriv jobs do not have that terminal. Do not claim XM order execution is operational until a Windows runner with a signed-in XM DEMO terminal is verified.

## Proposed V2
- Keep Deriv DEMO on its existing GitHub-hosted workflow unchanged.
- GitHub Actions orchestrates XM validation, testing, research, artifact collection and status.
- A dedicated Windows self-hosted GitHub Actions runner (on notebook for testing, Windows VPS for reliable unattended service) runs the XM DEMO execution worker beside installed XM MT5 terminal.
- Never place orders in generic pull-request or untrusted workflows. Protect runner with dedicated labels, least privileges, trusted branch and no public fork PR access.
- Laptop sleep, Windows updates, terminal disconnect, runner offline or broker downtime must stop new entries safely and alert; GitHub scheduler cannot guarantee exact timing.
- Keep separate broker data, positions, margin, equity, fees, slippage, incidents and stop-risk. Do not mix USD results across brokers without normalization.

## Order-safety design
1. Read-only connectivity/terminal account-type check, symbol specifications and price-feed validation.
2. Execution disabled by default; require verified DEMO server/account, local allow-demo flag, trade idempotency, max spread, margin floor, risk limit, order timeout, SL/TP and reconciliation before any order.
3. Reject any real account, absent terminal, stale quotes, duplicate signal, inconsistent order/fill state or failed reconciliation.
4. Explicitly disable real-money trading; never put broker passwords in repository or GitHub artifacts.
5. Backtest/forward-test in isolated research accounts before promoting strategy.

## Implementation gates
- Windows runner installed and online; terminal and DEMO account verified.
- No-order health probe succeeds repeatedly.
- Tests cover real-account rejection, disconnects, duplicates, rounding, stale quote, order rejection and recovery.
- Separate XM demo audit trail and loss-first daily reports.
- Only after review, enable demo orders and monitor them; keep Deriv runner untouched.

## Alternatives
For notebook-free 24/5 XM execution, use a persistent Windows VPS hosting MT5 and the runner, or a broker-authorized API if actually available and verified. Do not assume XM provides a native GitHub-compatible REST trading API.

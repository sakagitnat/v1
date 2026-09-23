# Runtime repair / Claude handoff — 2026-09-23

PR #14 merged into runtime as 7ad536a05d7f4e702f0433dc9cf4a24fc50af5b9.
Reran failed workflow 35873570386 (attempt 2, job 107268394714).
Broker/scheduler step succeeded, but state publication failed:
`cannot pull with rebase: You have unstaged changes`.
The previous hard-coded staging list omitted cfd_lab_observations.jsonl.
A PAPER-FORWARD close was printed, but the state commit did not reach GitHub;
do not treat that log line as a durably recorded trade or broker fill.

This repair stages all tracked state updates and cfd_*.json/jsonl outputs,
and archives a runtime snapshot before attempting publication in both main
scheduler and watchdog. A scoped push trigger on main's trading workflow
runs the repaired workflow after deployment; all broker gates remain DEMO.
This is a stopgap for the existing architecture, not a durable external DB.

Scheduler fixes:
- Keep tracked entry metadata until sell confirmation and accounting finish.
- Reject a close that still appears in broker portfolio.
- Read realized profit from the specific settled USD contract, using
  proposal_open_contract; accept numeric strings but reject unconfirmed,
  mismatched, non-finite or missing results. No aggregate-balance P&L guesses.
- External closes must all have confirmed settlements before local processing.
- Correct observation-count logging (the function returns a list).

Official API reference consulted:
https://developers.deriv.com/comparison/proposal-open-contract/
Actual settled-contract response compatibility still needs broker validation.

Validation: 501 offline tests pass, including the existing suite, real local
Git staging regression, failure injection at sell/balance/confirmation/
settlement, demo isolation, bounded connection retry and contract P&L parsing.

Outstanding: exactly-once accounting across process interruption, transactional
journal, persistent service and coordinated ownership across all research
writers, four-horizon quota execution, realistic simulation and migration.
Do not call this the completed rebuild. Contract settlement failure deliberately
retains recovery metadata and aborts this scheduler evaluation. There is no
claim that a direct Claude session has read this repository handoff.

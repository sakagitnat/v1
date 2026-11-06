"""Virtual capital accounting for the Deriv demo account.

Deriv's demo signup fixes the broker balance at roughly $10,000, with no
API to reset it to an arbitrary amount (see scripts/burn_demo_balance.py's
docstring -- now deprecated -- for the workaround this replaces). The
user's real intended starting capital is $100, so every risk/performance
calculation on the demo account must be computed from a *virtual* equity
rebased onto that $100, never from the raw ~$10,000 broker balance
directly. See docs/VISION.md's "Capital model" section for the full
rationale; this module is that rule made executable.

Real accounts are unaffected: with real money, the broker balance already
*is* the real number, so it passes through unchanged (see
equity_for_account below).
"""


def virtual_equity(broker_balance: float, broker_baseline: float, virtual_starting_capital: float) -> float:
    """virtual_equity = virtual_starting_capital + (broker_balance - broker_baseline).

    broker_baseline is the broker balance recorded the first time this
    system ever saw the demo account (see trading.cfd.state.
    set_broker_baseline, called once and never overwritten). Every dollar
    of P&L the broker balance moves by after that -- gain or loss -- is
    credited or debited 1:1 onto the virtual account, so virtual equity
    tracks the exact same trading performance as the real balance, just
    rebased onto a number that reflects the intended starting capital
    instead of Deriv's fixed demo default.

    Example: baseline=10000, virtual_starting_capital=100.
      broker_balance=10010 -> virtual_equity=110
      broker_balance=9980  -> virtual_equity=80
    """
    return virtual_starting_capital + (broker_balance - broker_baseline)


def equity_for_account(
    broker_balance: float,
    account_type: str,
    broker_baseline: float | None,
    virtual_starting_capital: float,
) -> float:
    """The equity value every risk/performance calculation should use:
    virtual (rebased) equity for a demo account once a baseline has been
    recorded, the raw broker balance for a real account (real money needs
    no rebasing -- it already is what it is) or for a demo account before
    any baseline exists yet (the caller is expected to record one via
    trading.cfd.state.set_broker_baseline before relying on this path)."""
    if account_type != "demo" or broker_baseline is None:
        return broker_balance
    return virtual_equity(broker_balance, broker_baseline, virtual_starting_capital)

from trading.cfd.capital import equity_for_account, virtual_equity


def test_virtual_equity_tracks_gain_1_to_1():
    # baseline 10000, virtual start 100 -> broker balance 10010 means the
    # broker gained 10, so virtual equity should be 100 + 10 = 110.
    assert virtual_equity(broker_balance=10010, broker_baseline=10000, virtual_starting_capital=100) == 110


def test_virtual_equity_tracks_loss_1_to_1():
    assert virtual_equity(broker_balance=9980, broker_baseline=10000, virtual_starting_capital=100) == 80


def test_virtual_equity_at_baseline_equals_starting_capital():
    assert virtual_equity(broker_balance=10000, broker_baseline=10000, virtual_starting_capital=100) == 100


def test_equity_for_account_rebases_demo_once_baseline_exists():
    equity = equity_for_account(
        broker_balance=10500, account_type="demo", broker_baseline=10000, virtual_starting_capital=100
    )
    assert equity == 600


def test_equity_for_account_passes_through_real_account_unchanged():
    # Real money is real money -- never rebased, regardless of any baseline.
    equity = equity_for_account(
        broker_balance=250.0, account_type="real", broker_baseline=10000, virtual_starting_capital=100
    )
    assert equity == 250.0


def test_equity_for_account_passes_through_demo_before_any_baseline_exists():
    # No baseline recorded yet -- caller is expected to record one before
    # relying on this path; falling back to the raw balance rather than
    # crashing or guessing keeps a first run from blowing up.
    equity = equity_for_account(
        broker_balance=10000.0, account_type="demo", broker_baseline=None, virtual_starting_capital=100
    )
    assert equity == 10000.0

from trading.cfd.scheduler import _reconcile_closed_trades


def _meta(**overrides):
    base = {
        "instrument": "frxXAUUSD",
        "strategy": "ema_crossover",
        "side": "long",
        "entry_time": "2026-01-01T00:00:00+00:00",
        "entry_price": 2000.0,
        "stake": 10.0,
        "risk_amount": 1.0,
        "equity_before": 100.0,
    }
    base.update(overrides)
    return base


def test_no_disappeared_contracts_returns_nothing():
    tracked = {"1": _meta()}
    assert _reconcile_closed_trades(tracked, currently_open_ids={1}, equity_now=100.0) == []


def test_single_disappeared_contract_gets_exact_pnl():
    tracked = {"1": _meta(equity_before=100.0)}
    records = _reconcile_closed_trades(tracked, currently_open_ids=set(), equity_now=112.0)
    assert len(records) == 1
    assert records[0].contract_id == 1
    assert records[0].pnl == 12.0
    assert records[0].equity_after == 112.0
    assert "externally" in records[0].exit_reason


def test_multiple_simultaneous_disappearances_are_unattributed():
    tracked = {"1": _meta(equity_before=100.0), "2": _meta(equity_before=100.0)}
    records = _reconcile_closed_trades(tracked, currently_open_ids=set(), equity_now=105.0)
    assert len(records) == 2
    assert all(r.pnl is None for r in records)
    assert all(r.equity_after is None for r in records)


def test_only_disappeared_contracts_are_included():
    tracked = {"1": _meta(), "2": _meta()}
    records = _reconcile_closed_trades(tracked, currently_open_ids={2}, equity_now=90.0)
    assert len(records) == 1
    assert records[0].contract_id == 1

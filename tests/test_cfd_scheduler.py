from trading.cfd.scheduler import _legs_by_strategy, _owned_by, _reconcile_closed_trades, _reconcile_unknown_positions, _reserved_stake_for_open_ids


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


def test_single_disappeared_contract_does_not_guess_from_balance():
    tracked = {"1": _meta(equity_before=100.0)}
    records = _reconcile_closed_trades(tracked, currently_open_ids=set(), equity_now=112.0)
    assert len(records) == 1
    assert records[0].contract_id == 1
    assert records[0].pnl is None
    assert records[0].equity_after is None
    assert "externally" in records[0].exit_reason


def test_multiple_simultaneous_disappearances_are_unattributed():
    tracked = {"1": _meta(equity_before=100.0), "2": _meta(equity_before=100.0)}
    records = _reconcile_closed_trades(tracked, currently_open_ids=set(), equity_now=105.0)
    assert len(records) == 2
    assert all(r.pnl is None for r in records)
    assert all(r.equity_after is None for r in records)


def test_multiple_closes_use_individual_contract_results_not_shared_balance():
    tracked = {"1": _meta(), "2": _meta()}
    records = _reconcile_closed_trades(tracked, set(), 9999, {1: 3.5, 2: -1.25})
    assert {r.contract_id: r.pnl for r in records} == {1: 3.5, 2: -1.25}


def test_only_disappeared_contracts_are_included():
    tracked = {"1": _meta(), "2": _meta()}
    records = _reconcile_closed_trades(tracked, currently_open_ids={2}, equity_now=90.0)
    assert len(records) == 1
    assert records[0].contract_id == 1


def test_reconciled_record_carries_over_the_regime_recorded_at_entry():
    tracked = {"1": _meta(regime="trending")}
    records = _reconcile_closed_trades(tracked, currently_open_ids=set(), equity_now=100.0)
    assert records[0].regime == "trending"


def _leg(contract_id, instrument="frxXAUUSD", side="long"):
    return {"contract_id": contract_id, "instrument": instrument, "side": side}


def test_a_known_tracked_contract_is_neither_adopted_nor_foreign():
    positions = {"frxXAUUSD": [_leg(1)]}
    tracked_open = {"1": _meta()}
    adoptions, foreign = _reconcile_unknown_positions(positions, tracked_open, pending_entries={})
    assert adoptions == []
    assert foreign == []


def test_unknown_contract_with_no_pending_entry_is_foreign():
    positions = {"frxXAUUSD": [_leg(1)]}
    adoptions, foreign = _reconcile_unknown_positions(positions, tracked_open={}, pending_entries={})
    assert adoptions == []
    assert len(foreign) == 1
    assert foreign[0] == {"contract_id": 1, "instrument": "frxXAUUSD", "side": "long"}


def test_unknown_contract_matching_a_pending_entry_is_adopted():
    positions = {"frxXAUUSD": [_leg(1)]}
    pending = {"frxXAUUSD": {"legs": [_meta(leg="runner")]}}
    adoptions, foreign = _reconcile_unknown_positions(positions, tracked_open={}, pending_entries=pending)
    assert foreign == []
    assert len(adoptions) == 1
    assert adoptions[0][0] == 1
    assert adoptions[0][1]["leg"] == "runner"


def test_both_legs_of_a_split_entry_are_adopted_in_order():
    positions = {"frxXAUUSD": [_leg(1), _leg(2)]}
    pending = {"frxXAUUSD": {"legs": [_meta(leg="scalp"), _meta(leg="runner")]}}
    adoptions, foreign = _reconcile_unknown_positions(positions, tracked_open={}, pending_entries=pending)
    assert foreign == []
    assert [a[1]["leg"] for a in adoptions] == ["scalp", "runner"]
    assert [a[0] for a in adoptions] == [1, 2]


def test_more_unknown_contracts_than_pending_legs_are_partly_foreign():
    # e.g. the pending entry only describes one leg, but two contracts
    # turned up -- the extra one is never assumed to be ours too.
    positions = {"frxXAUUSD": [_leg(1), _leg(2)]}
    pending = {"frxXAUUSD": {"legs": [_meta(leg="runner")]}}
    adoptions, foreign = _reconcile_unknown_positions(positions, tracked_open={}, pending_entries=pending)
    assert len(adoptions) == 1
    assert len(foreign) == 1


def test_pending_entry_for_a_different_instrument_does_not_cover_this_one():
    positions = {"frxEURUSD": [_leg(1, instrument="frxEURUSD")]}
    pending = {"frxXAUUSD": {"legs": [_meta(leg="runner")]}}
    adoptions, foreign = _reconcile_unknown_positions(positions, tracked_open={}, pending_entries=pending)
    assert adoptions == []
    assert len(foreign) == 1
    assert foreign[0]["instrument"] == "frxEURUSD"


def test_mixed_known_and_unknown_legs_on_the_same_instrument():
    positions = {"frxXAUUSD": [_leg(1), _leg(2)]}
    tracked_open = {"1": _meta()}  # contract 1 already known
    pending = {"frxXAUUSD": {"legs": [_meta(leg="runner")]}}
    adoptions, foreign = _reconcile_unknown_positions(positions, tracked_open, pending)
    assert len(adoptions) == 1
    assert adoptions[0][0] == 2
    assert foreign == []


# Revision 3 gap #3 (docs/ARCHITECTURE_AUDIT.md): an instrument can now
# hold independent positions from more than one ACTIVE strategy at once,
# so exit management and new-entry eligibility operate per strategy
# group, not per instrument as a whole -- _legs_by_strategy is the split.

def test_legs_by_strategy_groups_two_legs_of_one_entry_together():
    legs = [_leg(1), _leg(2)]
    tracked_open = {"1": _meta(strategy="ema_crossover@v1", leg="scalp"), "2": _meta(strategy="ema_crossover@v1", leg="runner")}
    groups = _legs_by_strategy(legs, tracked_open)
    assert set(groups.keys()) == {"ema_crossover@v1"}
    assert len(groups["ema_crossover@v1"]) == 2


def test_legs_by_strategy_splits_two_different_strategies_on_one_instrument():
    legs = [_leg(1), _leg(2)]
    tracked_open = {
        "1": _meta(strategy="ema_crossover@v1", leg="runner"),
        "2": _meta(strategy="mean_reversion@v1", leg="runner", side="short"),
    }
    groups = _legs_by_strategy(legs, tracked_open)
    assert set(groups.keys()) == {"ema_crossover@v1", "mean_reversion@v1"}
    assert groups["ema_crossover@v1"][0]["contract_id"] == 1
    assert groups["mean_reversion@v1"][0]["contract_id"] == 2


def test_legs_by_strategy_groups_untracked_legs_under_empty_tag():
    legs = [_leg(1)]
    groups = _legs_by_strategy(legs, tracked_open={})
    assert set(groups.keys()) == {""}
    assert groups[""][0]["contract_id"] == 1


def test_reserved_stake_counts_only_contracts_still_open():
    tracked = {
        "1": _meta(stake=1.0),
        "2": _meta(stake=2.5),
        "3": _meta(stake=4.0),
    }
    assert _reserved_stake_for_open_ids(tracked, {1, 3}) == 5.0


def test_reserved_stake_restores_cash_equity_after_entry():
    # Deriv cash falls from 10000 to 9999 after paying a $1 stake.
    # Adding the still-open cost basis back means account equity remains
    # 10000, so the virtual $100 ledger remains $100 until P&L is realized.
    tracked = {"123": _meta(stake=1.0)}
    broker_cash = 9999.0
    reconstructed = broker_cash + _reserved_stake_for_open_ids(tracked, {123})
    assert reconstructed == 10000.0


# _owned_by keeps each isolated $100 account's positions invisible to every
# other account's exit/entry/risk accounting -- without it, run_once() would
# adopt a champion/research account's unrecognized strategy tag under its
# own "sole ACTIVE strategy" fallback and mismanage a position it doesn't own.

def test_owned_by_is_true_for_a_matching_virtual_account():
    assert _owned_by(_meta(virtual_account_id="core_h1"), "core_h1") is True


def test_owned_by_is_true_for_legacy_metadata_with_no_virtual_account_tag():
    assert _owned_by(_meta(), "core_h1") is True


def test_owned_by_is_false_for_a_different_virtual_account():
    assert _owned_by(_meta(virtual_account_id="champion_m30"), "core_h1") is False

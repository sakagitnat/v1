from trading.cfd.portfolio_allocator import (
    MIN_TRADES_FOR_WEIGHTING,
    WEIGHT_FLOOR,
    compute_allocations,
    risk_scale_factor,
)
from trading.cfd.strategy_registry import StrategyEntry


def _entry(name, version="v1"):
    return StrategyEntry(
        name=name, version=version, params={}, state="ACTIVE",
        created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
    )


def _trade(pnl, strategy, contract_id):
    return {
        "contract_id": contract_id, "instrument": "frxXAUUSD", "strategy": strategy, "side": "long",
        "entry_time": "2026-01-01T00:00:00+00:00", "exit_time": "2026-01-01T01:00:00+00:00",
        "entry_price": 2000.0, "stake": 10.0, "risk_amount": 1.0, "pnl": pnl,
    }


def test_no_active_entries_returns_empty():
    assert compute_allocations([], []) == {}


def test_single_active_entry_gets_full_weight():
    assert compute_allocations([], [_entry("a")]) == {"a@v1": 1.0}


def test_entries_with_no_trade_history_split_evenly():
    weights = compute_allocations([], [_entry("a"), _entry("b")])
    assert weights == {"a@v1": 0.5, "b@v1": 0.5}


def test_entries_below_min_trades_treated_as_breakeven_not_penalized():
    # 3 losing trades each -- not enough history to weight by, so both
    # still land at the floor score and split evenly, same as no history.
    trades = [_trade(-5.0, "a@v1", i) for i in range(3)] + [_trade(-5.0, "b@v1", 100 + i) for i in range(3)]
    weights = compute_allocations(trades, [_entry("a"), _entry("b")])
    assert weights == {"a@v1": 0.5, "b@v1": 0.5}


def test_higher_expectancy_strategy_gets_more_weight():
    good = [_trade(2.0, "a@v1", i) for i in range(MIN_TRADES_FOR_WEIGHTING)]
    bad = [_trade(-1.0, "b@v1", 100 + i) for i in range(MIN_TRADES_FOR_WEIGHTING)]
    weights = compute_allocations(good + bad, [_entry("a"), _entry("b")])
    assert weights["a@v1"] > weights["b@v1"]
    assert weights["a@v1"] + weights["b@v1"] == 1.0


def test_losing_strategy_never_drops_below_the_floor_share():
    # A badly losing strategy still gets the WEIGHT_FLOOR score, same as
    # breakeven -- zeroing it out is decay_supervisor's job, not this.
    good = [_trade(5.0, "a@v1", i) for i in range(MIN_TRADES_FOR_WEIGHTING)]
    bad = [_trade(-5.0, "b@v1", 100 + i) for i in range(MIN_TRADES_FOR_WEIGHTING)]
    weights = compute_allocations(good + bad, [_entry("a"), _entry("b")])
    expected_total = WEIGHT_FLOOR + (WEIGHT_FLOOR + 5.0)
    assert abs(weights["b@v1"] - WEIGHT_FLOOR / expected_total) < 1e-9


def test_weights_always_sum_to_one_across_three_strategies():
    trades = (
        [_trade(3.0, "a@v1", i) for i in range(MIN_TRADES_FOR_WEIGHTING)]
        + [_trade(-2.0, "b@v1", 100 + i) for i in range(MIN_TRADES_FOR_WEIGHTING)]
        + [_trade(1.0, "c@v1", 200 + i) for i in range(3)]  # too little history
    )
    weights = compute_allocations(trades, [_entry("a"), _entry("b"), _entry("c")])
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_risk_scale_factor_at_equal_weight_is_one():
    assert risk_scale_factor(weight=0.5, n_active=2) == 1.0


def test_risk_scale_factor_never_exceeds_one():
    assert risk_scale_factor(weight=0.9, n_active=2) == 1.0


def test_risk_scale_factor_below_equal_weight_scales_down():
    assert risk_scale_factor(weight=0.1, n_active=2) == 0.2


def test_risk_scale_factor_with_no_active_strategies_defaults_to_one():
    assert risk_scale_factor(weight=0.0, n_active=0) == 1.0

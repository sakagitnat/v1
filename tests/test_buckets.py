from trading.execution import buckets


def test_load_buckets_defaults_to_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(buckets, "_BUCKETS_PATH", tmp_path / "buckets.json")
    assert buckets.load_buckets() == {}


def test_init_buckets_if_needed_creates_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(buckets, "_BUCKETS_PATH", tmp_path / "buckets.json")
    result = buckets.init_buckets_if_needed()
    assert result == {
        "safe": {"cash": 0.0, "strategy": "mean_reversion"},
        "risk1": {"cash": 0.0, "strategy": "breakout"},
    }
    assert buckets.load_buckets() == result


def test_init_buckets_if_needed_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(buckets, "_BUCKETS_PATH", tmp_path / "buckets.json")
    buckets.init_buckets_if_needed()
    buckets.save_buckets({"safe": {"cash": 50.0, "strategy": "mean_reversion"}, "risk1": {"cash": 10.0, "strategy": "breakout"}})
    result = buckets.init_buckets_if_needed()  # should NOT reset an already-populated ledger
    assert result["safe"]["cash"] == 50.0
    assert result["risk1"]["cash"] == 10.0


def test_rebalance_splits_growth_capital_by_safe_fraction():
    b = {"safe": {"cash": 0.0, "strategy": "mean_reversion"}, "risk1": {"cash": 0.0, "strategy": "breakout"}}
    result = buckets.rebalance(b, growth_capital=100.0, safe_fraction=0.5)
    assert result["safe"]["cash"] == 50.0
    assert result["risk1"]["cash"] == 50.0


def test_rebalance_never_reduces_existing_cash():
    b = {"safe": {"cash": 80.0, "strategy": "mean_reversion"}, "risk1": {"cash": 20.0, "strategy": "breakout"}}
    # growth_capital shrank (e.g. a losing day) -- targets are now below current cash
    result = buckets.rebalance(b, growth_capital=40.0, safe_fraction=0.5)
    assert result["safe"]["cash"] == 80.0
    assert result["risk1"]["cash"] == 20.0


def test_rebalance_tops_up_toward_target_without_double_counting():
    b = {"safe": {"cash": 30.0, "strategy": "mean_reversion"}, "risk1": {"cash": 10.0, "strategy": "breakout"}}
    result = buckets.rebalance(b, growth_capital=100.0, safe_fraction=0.5)
    assert result["safe"]["cash"] == 50.0  # topped up from 30 to the 50 target
    assert result["risk1"]["cash"] == 50.0  # topped up from 10 to the 50 target


def test_rebalance_refills_blown_risk_bucket_before_others():
    b = {
        "safe": {"cash": 50.0, "strategy": "mean_reversion"},
        "risk1": {"cash": 0.0, "strategy": "breakout"},  # blown
        "risk2": {"cash": 40.0, "strategy": "breakout"},  # healthy, already near target
    }
    # risk pool target = 100 * 0.5 = 50; already have 0 + 40 = 40; 10 available to add
    result = buckets.rebalance(b, growth_capital=100.0, safe_fraction=0.5)
    assert result["risk1"]["cash"] == 10.0  # blown bucket gets all the newly available cash
    assert result["risk2"]["cash"] == 40.0  # healthy bucket untouched this round


def test_rebalance_splits_across_multiple_healthy_risk_buckets():
    b = {
        "safe": {"cash": 50.0, "strategy": "mean_reversion"},
        "risk1": {"cash": 10.0, "strategy": "breakout"},
        "risk2": {"cash": 10.0, "strategy": "breakout"},
    }
    # risk pool target = 100 * 0.5 = 50; already have 20; 30 available, split evenly (both healthy)
    result = buckets.rebalance(b, growth_capital=100.0, safe_fraction=0.5)
    assert result["risk1"]["cash"] == 25.0
    assert result["risk2"]["cash"] == 25.0


def test_is_blown():
    assert buckets.is_blown({"cash": 0.0}) is True
    assert buckets.is_blown({"cash": 4.99}) is True
    assert buckets.is_blown({"cash": 5.0}) is False
    assert buckets.is_blown({"cash": 100.0}) is False

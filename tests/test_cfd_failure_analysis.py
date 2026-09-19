from trading.cfd import strategy_registry as reg
from trading.cfd.failure_analysis import classify_loss, detect_degradation, summarize_losses
from trading.cfd.strategy_registry import LifecycleState


def _trade(pnl, risk_amount=1.0, regime=None, strategy="ema_crossover@v1",
           exit_time="2026-01-01T01:00:00+00:00", contract_id=1):
    return {
        "contract_id": contract_id,
        "instrument": "frxXAUUSD",
        "strategy": strategy,
        "side": "long",
        "entry_time": "2026-01-01T00:00:00+00:00",
        "exit_time": exit_time,
        "entry_price": 2000.0,
        "stake": 10.0,
        "risk_amount": risk_amount,
        "pnl": pnl,
        "regime": regime,
    }


def test_classify_not_a_loss():
    assert classify_loss(_trade(pnl=5.0)) == "not_a_loss"
    assert classify_loss(_trade(pnl=0.0)) == "not_a_loss"


def test_classify_unattributed_when_pnl_unknown():
    assert classify_loss(_trade(pnl=None)) == "unattributed"


def test_classify_normal_statistical_loss_near_budgeted_risk():
    # pnl == -risk_amount is exactly the budgeted loss -- the ordinary case.
    assert classify_loss(_trade(pnl=-1.0, risk_amount=1.0)) == "normal_statistical_loss"


def test_classify_excessive_risk_when_loss_far_exceeds_budget():
    # R multiple -1.0 / ... -> pnl=-2.0, risk_amount=1.0 => R=-2.0, past -1.5 threshold
    assert classify_loss(_trade(pnl=-2.0, risk_amount=1.0)) == "excessive_risk"


def test_classify_handles_missing_risk_amount_gracefully():
    assert classify_loss(_trade(pnl=-5.0, risk_amount=0.0)) == "normal_statistical_loss"


def test_classify_regime_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")
    reg.register("ema_crossover", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    trade = _trade(pnl=-0.5, risk_amount=1.0, regime="ranging", strategy="ema_crossover@v1")
    assert classify_loss(trade) == "regime_mismatch"


def test_classify_no_mismatch_when_regime_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")
    reg.register("ema_crossover", "v1", {}, initial_state=LifecycleState.ACTIVE, regimes=["trending"])
    trade = _trade(pnl=-0.5, risk_amount=1.0, regime="trending", strategy="ema_crossover@v1")
    assert classify_loss(trade) == "normal_statistical_loss"


def test_classify_unregistered_strategy_falls_back_to_normal(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")
    trade = _trade(pnl=-0.5, risk_amount=1.0, regime="ranging", strategy="nonexistent@v9")
    assert classify_loss(trade) == "normal_statistical_loss"


def test_summarize_losses_buckets_and_totals(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "cfd_strategy_registry.json")
    trades = [
        _trade(pnl=-1.0, risk_amount=1.0, contract_id=1),  # normal
        _trade(pnl=-2.0, risk_amount=1.0, contract_id=2),  # excessive
        _trade(pnl=5.0, contract_id=3),  # win, excluded
        _trade(pnl=None, contract_id=4),  # unattributed, excluded (only losses summarized)
    ]
    summary = summarize_losses(trades)
    assert summary["normal_statistical_loss"]["count"] == 1
    assert summary["normal_statistical_loss"]["contract_ids"] == [1]
    assert summary["excessive_risk"]["count"] == 1
    assert summary["excessive_risk"]["total_pnl"] == -2.0
    assert "not_a_loss" not in summary
    assert "unattributed" not in summary


def test_detect_degradation_returns_none_with_too_little_history():
    trades = [_trade(pnl=1.0, contract_id=i) for i in range(5)]
    assert detect_degradation(trades, "ema_crossover@v1", recent_window=10) is None


def test_detect_degradation_flags_expectancy_turning_negative():
    prior = [_trade(pnl=2.0, contract_id=i, exit_time=f"2026-01-01T{i:02d}:00:00+00:00") for i in range(10)]
    recent = [_trade(pnl=-1.0, contract_id=100 + i, exit_time=f"2026-01-02T{i:02d}:00:00+00:00") for i in range(10)]
    result = detect_degradation(prior + recent, "ema_crossover@v1", recent_window=10)
    assert result["degraded"] is True
    assert result["prior_expectancy"] == 2.0
    assert result["recent_expectancy"] == -1.0


def test_detect_degradation_flags_a_large_relative_drop_even_if_still_positive():
    prior = [_trade(pnl=10.0, contract_id=i, exit_time=f"2026-01-01T{i:02d}:00:00+00:00") for i in range(10)]
    recent = [_trade(pnl=1.0, contract_id=100 + i, exit_time=f"2026-01-02T{i:02d}:00:00+00:00") for i in range(10)]
    result = detect_degradation(prior + recent, "ema_crossover@v1", recent_window=10)
    assert result["degraded"] is True  # 90% drop, past the 50% bar


def test_detect_degradation_not_flagged_for_stable_performance():
    trades = [_trade(pnl=1.0, contract_id=i, exit_time=f"2026-01-01T{i:02d}:00:00+00:00") for i in range(20)]
    result = detect_degradation(trades, "ema_crossover@v1", recent_window=10)
    assert result["degraded"] is False


def test_detect_degradation_ignores_other_strategies_trades():
    own = [_trade(pnl=1.0, contract_id=i, strategy="ema_crossover@v1", exit_time=f"2026-01-01T{i:02d}:00:00+00:00") for i in range(20)]
    other = [_trade(pnl=-99.0, contract_id=100 + i, strategy="donchian_breakout@v1", exit_time=f"2026-01-01T{i:02d}:00:00+00:00") for i in range(20)]
    result = detect_degradation(own + other, "ema_crossover@v1", recent_window=10)
    assert result["degraded"] is False
    assert result["recent_expectancy"] == 1.0

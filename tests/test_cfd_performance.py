from trading.cfd.performance import compute_performance


def _trade(pnl, risk_amount=1.0, strategy="ema_crossover", side="long", regime=None,
           entry="2026-01-01T00:00:00+00:00", exit="2026-01-01T01:00:00+00:00"):
    return {
        "contract_id": 1,
        "instrument": "frxXAUUSD",
        "strategy": strategy,
        "side": side,
        "entry_time": entry,
        "exit_time": exit,
        "entry_price": 2000.0,
        "stake": 10.0,
        "risk_amount": risk_amount,
        "exit_price": 2010.0,
        "pnl": pnl,
        "equity_before": 100.0,
        "equity_after": 100.0 + (pnl or 0),
        "exit_reason": "signal_exit: test",
        "regime": regime,
    }


def test_empty_trade_list_returns_zeroed_metrics():
    metrics = compute_performance([])
    assert metrics["trade_count"] == 0
    assert metrics["net_return"] == 0.0
    assert metrics["win_rate_pct"] == 0.0
    assert metrics["by_strategy"] == {}


def test_unattributed_trades_are_excluded_from_pnl_metrics_but_counted():
    trades = [_trade(pnl=None), _trade(pnl=10.0)]
    metrics = compute_performance(trades, starting_equity=100.0)
    assert metrics["trade_count"] == 2
    assert metrics["priced_trade_count"] == 1
    assert metrics["unattributed_trade_count"] == 1
    assert metrics["net_return"] == 10.0  # not diluted by the unattributed trade
    assert metrics["expectancy"] == 10.0  # averaged over priced trades only, not all trades


def test_basic_metrics_over_two_priced_trades():
    trades = [_trade(pnl=10.0), _trade(pnl=-5.0)]
    metrics = compute_performance(trades, starting_equity=100.0)
    assert metrics["net_return"] == 5.0
    assert metrics["win_rate_pct"] == 50.0
    assert metrics["avg_win"] == 10.0
    assert metrics["avg_loss"] == -5.0
    assert metrics["profit_factor"] == 2.0  # 10 / 5
    assert metrics["avg_r_multiple"] == (10.0 / 1.0 + -5.0 / 1.0) / 2


def test_all_losses_gives_zero_profit_factor_not_a_crash():
    trades = [_trade(pnl=-1.0), _trade(pnl=-2.0)]
    metrics = compute_performance(trades, starting_equity=100.0)
    assert metrics["profit_factor"] == 0.0  # no gross win at all, not a ZeroDivisionError
    assert metrics["avg_win"] == 0.0


def test_all_wins_gives_no_profit_factor_no_losses_to_divide_by():
    trades = [_trade(pnl=1.0), _trade(pnl=2.0)]
    metrics = compute_performance(trades, starting_equity=100.0)
    assert metrics["profit_factor"] is None  # undefined (no losses), not a ZeroDivisionError
    assert metrics["avg_loss"] == 0.0


def test_max_drawdown_reflects_a_losing_streak_then_recovery():
    trades = [
        _trade(pnl=-20.0, entry="2026-01-01T00:00:00+00:00", exit="2026-01-01T01:00:00+00:00"),
        _trade(pnl=-20.0, entry="2026-01-01T01:00:00+00:00", exit="2026-01-01T02:00:00+00:00"),
        _trade(pnl=30.0, entry="2026-01-01T02:00:00+00:00", exit="2026-01-01T03:00:00+00:00"),
    ]
    metrics = compute_performance(trades, starting_equity=100.0)
    # equity: 100 -> 80 -> 60 -> 90; drawdown bottoms at 60 vs peak 100 = -40%
    assert metrics["max_drawdown_pct"] == -40.0
    assert metrics["longest_losing_streak"] == 2


def test_longest_losing_streak_does_not_span_a_win():
    trades = [
        _trade(pnl=-1.0, entry="2026-01-01T00:00:00+00:00", exit="2026-01-01T01:00:00+00:00"),
        _trade(pnl=5.0, entry="2026-01-01T01:00:00+00:00", exit="2026-01-01T02:00:00+00:00"),
        _trade(pnl=-1.0, entry="2026-01-01T02:00:00+00:00", exit="2026-01-01T03:00:00+00:00"),
    ]
    metrics = compute_performance(trades, starting_equity=100.0)
    assert metrics["longest_losing_streak"] == 1


def test_breakdowns_group_by_strategy_regime_side():
    trades = [
        _trade(pnl=10.0, strategy="ema_crossover", side="long", regime="trend"),
        _trade(pnl=-4.0, strategy="donchian_breakout", side="short", regime=None),
    ]
    metrics = compute_performance(trades, starting_equity=100.0)
    assert metrics["by_strategy"]["ema_crossover"]["net_pnl"] == 10.0
    assert metrics["by_strategy"]["donchian_breakout"]["net_pnl"] == -4.0
    assert metrics["by_side"]["long"]["trade_count"] == 1
    assert metrics["by_side"]["short"]["trade_count"] == 1
    assert metrics["by_regime"]["trend"]["trade_count"] == 1
    assert metrics["by_regime"]["unknown"]["trade_count"] == 1  # None regime bucketed, not dropped


def test_by_session_groups_by_entry_hour_bucket():
    trades = [
        _trade(pnl=1.0, entry="2026-01-01T03:00:00+00:00", exit="2026-01-01T04:00:00+00:00"),
        _trade(pnl=1.0, entry="2026-01-01T20:00:00+00:00", exit="2026-01-01T21:00:00+00:00"),
    ]
    metrics = compute_performance(trades, starting_equity=100.0)
    assert metrics["by_session"]["00-06 UTC"]["trade_count"] == 1
    assert metrics["by_session"]["18-24 UTC"]["trade_count"] == 1

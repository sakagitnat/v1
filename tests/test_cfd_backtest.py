import pandas as pd
import pytest

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.portfolio_risk import PortfolioRiskCeilings
from trading.strategy.base import Action, Signal


class _ScriptedStrategy:
    """Emits a fixed action per bar index, so the engine's mechanics can
    be tested without depending on EmaCrossoverStrategy's own logic."""

    def __init__(self, actions: dict[int, Signal]):
        self.actions = actions
        self._i = -1

    def prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        return bars.copy()

    def signal_for_row(self, instrument, row, prev_row, in_position):
        self._i += 1
        return self.actions.get(self._i, Signal(instrument, Action.HOLD, row["close"]))


def _bars(closes, highs=None, lows=None, start="2024-01-01"):
    idx = pd.date_range(start, periods=len(closes), freq="15min", tz="UTC")
    highs = highs or [max(c, c) for c in closes]
    lows = lows or closes
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes}, index=idx)


def test_long_trade_hits_take_profit_exactly_at_configured_level():
    closes = [100, 100, 100]
    highs = [100, 100, 110]  # bar 2's high pierces the target (105) without touching stop
    lows = [100, 100, 100]
    bars = {"XAU": _bars(closes, highs, lows)}

    # call index 0 fires on bar 1 (bar 0 only seeds prev_row, no signal_for_row call yet)
    actions = {0: Signal("XAU", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=105.0)}
    strategy = _ScriptedStrategy(actions)
    engine = CfdBacktestEngine(strategy, starting_equity=1000.0, risk_per_trade=0.01, multiplier=20)
    result = engine.run(bars)

    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["side"] == "long"
    assert trade["exit"] == 105.0  # filled at the configured target, not the bar's high
    # stake = risk_amount * entry / (multiplier * stop_distance) = 10 * 100 / (20 * 5) = 10
    assert trade["stake"] == 10.0
    # pnl = stake * multiplier * pct_move = 10 * 20 * (105-100)/100 = 10.0
    assert trade["pnl"] == 10.0


def test_short_trade_loss_is_capped_below_the_naive_risk_amount():
    # stop_distance (10) exceeds entry/multiplier (100/20=5), so the naive
    # dollar loss at the stop price (-risk_amount, -10) would exceed the
    # stake (5) sized for this trade -- Deriv's capped-loss guarantee means
    # the real max loss is the stake, not the configured risk_amount.
    closes = [100, 100, 100]
    highs = [100, 100, 130]  # blows straight through the stop (110) in one bar
    lows = [100, 100, 100]
    bars = {"XAU": _bars(closes, highs, lows)}

    actions = {0: Signal("XAU", Action.SELL, price=100.0, stop_price=110.0, take_profit_price=90.0)}
    strategy = _ScriptedStrategy(actions)
    engine = CfdBacktestEngine(strategy, starting_equity=1000.0, risk_per_trade=0.01, multiplier=20)
    result = engine.run(bars)

    trade = result["trades"][0]
    assert trade["side"] == "short"
    assert trade["exit"] == 110.0  # still fills at the configured stop, no slippage
    assert trade["stake"] == 5.0  # risk_amount * entry / (multiplier * stop_distance) = 10*100/(20*10)
    assert trade["pnl"] == -5.0  # capped at -stake, not the naive -risk_amount (-10)
    assert trade["pnl"] >= -trade["stake"]  # never worse than losing the whole stake


def test_exit_signal_closes_position_at_close_price():
    closes = [100, 100, 100, 103]
    bars = {"XAU": _bars(closes)}

    actions = {
        0: Signal("XAU", Action.BUY, price=100.0, stop_price=90.0, take_profit_price=140.0),
        1: Signal("XAU", Action.SELL, price=100.0, reason="reversal"),
    }
    strategy = _ScriptedStrategy(actions)
    engine = CfdBacktestEngine(strategy, starting_equity=1000.0, risk_per_trade=0.01, multiplier=20)
    result = engine.run(bars)

    assert len(result["trades"]) == 1
    assert result["trades"][0]["exit"] == 100.0  # bar 2's close, not bar 3's


def test_max_open_positions_blocks_a_second_symbol_entry():
    closes = [100, 100, 100]
    bars = {
        "A": _bars(closes),
        "B": _bars(closes),
    }
    actions = {1: Signal("_", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=110.0)}
    strategy_a = _ScriptedStrategy(actions)
    strategy_b = _ScriptedStrategy(actions)

    class _DualStrategy:
        def prepare(self, bars):
            return bars.copy()

        def signal_for_row(self, instrument, row, prev_row, in_position):
            s = strategy_a if instrument == "A" else strategy_b
            return s.signal_for_row(instrument, row, prev_row, in_position)

    engine = CfdBacktestEngine(_DualStrategy(), starting_equity=1000.0, max_open_positions=1)
    result = engine.run(bars)
    assert len(result["trades"]) == 0  # neither closed yet, but only one should have opened
    assert engine.risk.open_positions == 1


def test_portfolio_risk_governor_blocks_a_correlated_second_entry():
    # frxXAUUSD long and frxEURUSD long are both "USD weakens" bets (see
    # trading.cfd.portfolio_risk.CORRELATION_FACTORS) -- a tight correlated
    # ceiling must block the second entry even though max_open_positions
    # alone would have allowed it.
    closes = [100, 100, 100]
    bars = {"frxXAUUSD": _bars(closes), "frxEURUSD": _bars(closes)}
    actions = {1: Signal("_", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=110.0)}
    strategy_a = _ScriptedStrategy(actions)
    strategy_b = _ScriptedStrategy(actions)

    class _DualStrategy:
        def prepare(self, bars):
            return bars.copy()

        def signal_for_row(self, instrument, row, prev_row, in_position):
            s = strategy_a if instrument == "frxXAUUSD" else strategy_b
            return s.signal_for_row(instrument, row, prev_row, in_position)

    # risk_amount per entry = 1000 * 0.01 = $10; correlated ceiling of
    # 1.5% of $1000 ($15) allows the first $10 entry but blocks a second
    # correlated $10 entry (would total $20).
    ceilings = PortfolioRiskCeilings(
        max_thesis_risk_pct=1.0, max_correlated_risk_pct=0.015,
        max_portfolio_risk_pct=1.0, max_exposure_multiple=1000.0,
    )
    engine = CfdBacktestEngine(_DualStrategy(), starting_equity=1000.0, max_open_positions=5, ceilings=ceilings)
    result = engine.run(bars)
    assert len(result["trades"]) == 0  # neither closed yet
    assert engine.risk.open_positions == 1  # only one of the two correlated entries got through


def test_portfolio_risk_governor_allows_uncorrelated_entries_up_to_max_open_positions():
    closes = [100, 100, 100]
    bars = {"frxXAUUSD": _bars(closes), "frxUSDJPY": _bars(closes)}  # opposite USD-factor sign
    actions = {1: Signal("_", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=110.0)}
    strategy_a = _ScriptedStrategy(actions)
    strategy_b = _ScriptedStrategy(actions)

    class _DualStrategy:
        def prepare(self, bars):
            return bars.copy()

        def signal_for_row(self, instrument, row, prev_row, in_position):
            s = strategy_a if instrument == "frxXAUUSD" else strategy_b
            return s.signal_for_row(instrument, row, prev_row, in_position)

    ceilings = PortfolioRiskCeilings(
        max_thesis_risk_pct=1.0, max_correlated_risk_pct=0.015,
        max_portfolio_risk_pct=1.0, max_exposure_multiple=1000.0,
    )
    engine = CfdBacktestEngine(_DualStrategy(), starting_equity=1000.0, max_open_positions=5, ceilings=ceilings)
    result = engine.run(bars)
    assert engine.risk.open_positions == 2  # both got through -- opposite-signed factor, not correlated


def test_spread_cost_defaults_to_zero_and_does_not_affect_pnl():
    closes = [100, 100, 100]
    highs = [100, 100, 110]
    lows = [100, 100, 100]
    bars = {"XAU": _bars(closes, highs, lows)}
    actions = {0: Signal("XAU", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=105.0)}
    strategy = _ScriptedStrategy(actions)
    engine = CfdBacktestEngine(strategy, starting_equity=1000.0, risk_per_trade=0.01, multiplier=20)
    result = engine.run(bars)
    assert result["trades"][0]["pnl"] == 10.0
    assert result["trades"][0]["spread_cost"] == 0.0


def test_spread_cost_is_deducted_from_pnl_once_per_round_trip():
    closes = [100, 100, 100]
    highs = [100, 100, 110]
    lows = [100, 100, 100]
    bars = {"XAU": _bars(closes, highs, lows)}
    actions = {0: Signal("XAU", Action.BUY, price=100.0, stop_price=95.0, take_profit_price=105.0)}
    strategy = _ScriptedStrategy(actions)
    engine = CfdBacktestEngine(strategy, starting_equity=1000.0, risk_per_trade=0.01, multiplier=20, spread_pct=0.001)
    result = engine.run(bars)
    trade = result["trades"][0]
    # stake=10.0, multiplier=20 -> notional=200; spread_cost = 200*0.001 = 0.2
    assert trade["spread_cost"] == 0.2
    assert trade["pnl"] == 10.0 - 0.2


def test_daily_financing_accrues_against_equity_for_each_full_day_held():
    # A position opened and held across two UTC day boundaries before
    # closing on the third day -- financing should be charged twice
    # (once per boundary crossed while still open), not once per bar.
    idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    closes = [100, 100, 100, 100]
    bars = {"XAU": pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes}, index=idx)}
    actions = {0: Signal("XAU", Action.BUY, price=100.0, stop_price=50.0, take_profit_price=200.0)}
    strategy = _ScriptedStrategy(actions)
    engine = CfdBacktestEngine(
        strategy, starting_equity=1000.0, risk_per_trade=0.01, multiplier=20, daily_financing_pct=0.0001,
    )
    result = engine.run(bars)
    # stake = 10*100/(20*50) = 1.0 -> notional = 20; financing per day = 20*0.0001 = 0.002
    # position opens on bar index 1 (2024-01-02), stays open through bars 2 and 3 (two day
    # boundaries crossed: Jan2->Jan3, Jan3->Jan4) before never closing (no exit signal/stop/target hit).
    curve = result["equity_curve"]
    assert curve.iloc[-1] == pytest.approx(1000.0 - 2 * 0.002, abs=1e-9)


def test_equity_curve_reflects_unrealized_pnl_while_open():
    closes = [100, 100, 110]
    bars = {"XAU": _bars(closes)}
    actions = {1: Signal("XAU", Action.BUY, price=100.0, stop_price=50.0, take_profit_price=200.0)}
    strategy = _ScriptedStrategy(actions)
    engine = CfdBacktestEngine(strategy, starting_equity=1000.0, risk_per_trade=0.01, multiplier=20)
    result = engine.run(bars)

    curve = result["equity_curve"]
    # stake = 10*100/(20*50) = 1.0; unrealized at close=110 -> 1*20*10/100 = 2.0 above starting equity
    assert curve.iloc[-1] == 1002.0

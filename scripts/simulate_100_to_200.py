"""One-off: starting from exactly $100 with the real capital-floor ladder
active (capital_floor=100, ladder=True -- matching the live bot's actual
settings), how long would it have historically taken equity to first cross
$200, using the diversified watchlist and Breakout strategy?

Not a permanent script -- ad hoc, requested in chat.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.backtest.engine import BacktestEngine
from trading.config import settings
from trading.data.market_data import load_watchlist_bars
from trading.strategy.breakout import BreakoutStrategy

FETCH_START = "2019-01-01"
START_DATES = ["2020-01-01", "2021-01-01", "2022-01-01", "2023-01-01"]


def main():
    symbols = settings.watchlist
    print(f"Fetching bars for {symbols} ...")
    all_bars = load_watchlist_bars(symbols, start=FETCH_START)

    for start_date in START_DATES:
        bars = {s: df.loc[start_date:] for s, df in all_bars.items()}

        engine = BacktestEngine(
            strategy=BreakoutStrategy(),
            starting_equity=100.0,
            risk_per_trade=settings.risk_per_trade,
            max_open_positions=settings.max_open_positions,
            max_daily_loss_pct=settings.max_daily_loss_pct,
        )
        engine.risk.capital_floor = 100.0
        engine.risk.ladder = True

        result = engine.run(bars)
        curve = result["equity_curve"]
        if curve.empty:
            print(f"\nStarting {start_date}: no bars.")
            continue

        crossed = curve[curve >= 200.0]
        final = curve.iloc[-1]
        if not crossed.empty:
            cross_date = crossed.index[0]
            days = (cross_date - curve.index[0]).days
            print(
                f"\nStarting {start_date}: crossed $200 on {cross_date.date()} "
                f"({days} days / ~{days/365.25:.1f} years). Final equity ({curve.index[-1].date()}): {final:.2f}"
            )
        else:
            print(
                f"\nStarting {start_date}: never crossed $200 through {curve.index[-1].date()}. "
                f"Final equity: {final:.2f} ({len(result['trades'])} trades)"
            )


if __name__ == "__main__":
    main()

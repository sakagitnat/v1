import pandas as pd

from trading.backtest.metrics import compute_metrics
from trading.risk.risk_manager import RiskManager
from trading.strategy.base import Action


class BacktestEngine:
    """Event-driven daily-bar backtester.

    Equity tracks realized P&L (RiskManager.equity) plus the unrealized P&L of
    any bars currently held, so the returned equity curve reflects mark-to-market
    value even though the risk manager only updates on a closed trade.
    """

    def __init__(
        self,
        strategy,
        starting_equity: float = 100_000.0,
        risk_per_trade: float = 0.01,
        max_open_positions: int = 5,
        max_daily_loss_pct: float = 0.03,
    ):
        self.strategy = strategy
        self.risk = RiskManager(
            equity=starting_equity,
            risk_per_trade=risk_per_trade,
            max_open_positions=max_open_positions,
            max_daily_loss_pct=max_daily_loss_pct,
        )

    def run(self, price_data: dict[str, pd.DataFrame]) -> dict:
        prepared = {sym: self.strategy.prepare(df) for sym, df in price_data.items() if not df.empty}
        if not prepared:
            return {"equity_curve": pd.Series(dtype=float), "trades": [], "metrics": compute_metrics(pd.Series(dtype=float), [])}

        all_dates = sorted(set().union(*[set(df.index) for df in prepared.values()]))

        positions: dict[str, dict] = {}
        trades: list[dict] = []
        equity_points: list[tuple] = []
        last_date = None

        for date in all_dates:
            if last_date is not None and date.date() != last_date.date():
                self.risk.reset_day()
            last_date = date

            for sym, df in prepared.items():
                if date not in df.index:
                    continue
                row = df.loc[date]
                in_position = sym in positions
                signal = self.strategy.signal_for_row(sym, row, in_position)

                if in_position:
                    pos = positions[sym]
                    hit_stop = pos["stop"] is not None and row["low"] <= pos["stop"]
                    hit_target = pos["target"] is not None and row["high"] >= pos["target"]
                    should_exit = signal.action == Action.SELL or hit_stop or hit_target

                    if should_exit:
                        exit_price = pos["stop"] if hit_stop else (pos["target"] if hit_target else row["close"])
                        pnl = (exit_price - pos["entry"]) * pos["shares"]
                        trades.append(
                            {
                                "symbol": sym,
                                "entry_date": pos["entry_date"],
                                "exit_date": date,
                                "entry": pos["entry"],
                                "exit": exit_price,
                                "shares": pos["shares"],
                                "pnl": pnl,
                            }
                        )
                        self.risk.register_close(pnl)
                        del positions[sym]

                elif signal.action == Action.BUY and not self.risk.halted:
                    shares = self.risk.position_size(signal.price, signal.stop_price)
                    if shares > 0:
                        positions[sym] = {
                            "entry": signal.price,
                            "stop": signal.stop_price,
                            "target": signal.take_profit_price,
                            "shares": shares,
                            "entry_date": date,
                        }
                        self.risk.register_open()

            unrealized = sum(
                (prepared[sym].loc[date, "close"] - pos["entry"]) * pos["shares"]
                for sym, pos in positions.items()
                if date in prepared[sym].index
            )
            equity_points.append((date, self.risk.equity + unrealized))

        curve = pd.Series({d: v for d, v in equity_points}).sort_index()
        metrics = compute_metrics(curve, trades)
        return {"equity_curve": curve, "trades": trades, "metrics": metrics}

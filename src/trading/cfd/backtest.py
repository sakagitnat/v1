import pandas as pd

from trading.cfd.risk import CfdRiskManager
from trading.strategy.base import Action


def compute_cfd_metrics(equity_curve: pd.Series, trades: list[dict]) -> dict:
    """Same shape as trading.backtest.metrics.compute_metrics, but
    annualizes from the equity curve's actual elapsed calendar time
    instead of assuming 252 daily bars -- M15 forex/gold bars run at a
    completely different (and irregular, 24/5) frequency than the stock
    system's daily bars."""
    if equity_curve.empty:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "num_trades": 0,
            "win_rate_pct": 0.0,
            "final_equity": 0.0,
        }

    returns = equity_curve.pct_change().dropna()
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0] - 1
    elapsed_days = (equity_curve.index[-1] - equity_curve.index[0]).total_seconds() / 86400
    years = max(elapsed_days / 365.25, 1e-9)
    cagr = (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1.0

    bars_per_year = len(equity_curve) / years
    sharpe = 0.0
    if returns.std() > 0 and bars_per_year > 0:
        sharpe = (returns.mean() / returns.std()) * (bars_per_year**0.5)

    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    max_drawdown = drawdown.min()

    wins = [t for t in trades if t["pnl"] > 0]
    win_rate = len(wins) / len(trades) if trades else 0.0

    return {
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "num_trades": len(trades),
        "win_rate_pct": round(win_rate * 100, 2),
        "final_equity": round(float(equity_curve.iloc[-1]), 2),
    }


class CfdBacktestEngine:
    """Event-driven bar backtester for Deriv Multipliers strategies --
    the CFD/forex counterpart of trading.backtest.engine.BacktestEngine,
    different everywhere Deriv Multipliers differ from Alpaca whole-share
    equities: long AND short through one signal_for_row(instrument, row,
    prev_row, in_position) call; position sizing is a leveraged dollar
    "stake" (CfdRiskManager.stake_and_limits), not whole shares; P&L is
    multiplier * stake * pct_price_move, capped so a loss can never
    exceed the stake -- Deriv's capped-loss guarantee for this contract
    type, unlike a plain leveraged CFD where an adverse move can lose
    more than the margin put up.

    Stop-loss/take-profit fills execute at the exact configured price
    level, no slippage -- matching Deriv's own guaranteed-stop-out
    behavior for Multipliers (the real product's stop/take-profit levels
    are dollar P&L triggers Deriv itself executes exactly, not orders
    resting in a market that can gap past them)."""

    def __init__(
        self,
        strategy,
        starting_equity: float = 10_000.0,
        risk_per_trade: float = 0.01,
        max_open_positions: int = 3,
        max_daily_loss_pct: float = 0.03,
        multiplier: int = 20,
    ):
        self.strategy = strategy
        self.risk = CfdRiskManager(
            equity=starting_equity,
            risk_per_trade=risk_per_trade,
            max_open_positions=max_open_positions,
            max_daily_loss_pct=max_daily_loss_pct,
            multiplier=multiplier,
        )

    @staticmethod
    def _pnl(side: str, entry: float, exit_price: float, stake: float, multiplier: int) -> float:
        pct_move = (exit_price - entry) / entry if side == "long" else (entry - exit_price) / entry
        return max(stake * multiplier * pct_move, -stake)

    def run(self, price_data: dict[str, pd.DataFrame]) -> dict:
        prepared = {sym: self.strategy.prepare(df) for sym, df in price_data.items() if not df.empty}
        if not prepared:
            return {"equity_curve": pd.Series(dtype=float), "trades": [], "metrics": compute_cfd_metrics(pd.Series(dtype=float), [])}

        all_dates = sorted(set().union(*[set(df.index) for df in prepared.values()]))

        positions: dict[str, dict] = {}
        prev_rows: dict[str, pd.Series] = {}
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
                prev_row = prev_rows.get(sym)
                prev_rows[sym] = row
                if prev_row is None:
                    continue

                pos = positions.get(sym)
                in_position = pos["side"] if pos else None
                signal = self.strategy.signal_for_row(sym, row, prev_row, in_position)

                if pos is not None:
                    hit_stop = (pos["side"] == "long" and row["low"] <= pos["stop"]) or (
                        pos["side"] == "short" and row["high"] >= pos["stop"]
                    )
                    hit_target = (pos["side"] == "long" and row["high"] >= pos["target"]) or (
                        pos["side"] == "short" and row["low"] <= pos["target"]
                    )
                    is_exit_signal = (pos["side"] == "long" and signal.action == Action.SELL) or (
                        pos["side"] == "short" and signal.action == Action.BUY
                    )

                    if is_exit_signal or hit_stop or hit_target:
                        exit_price = pos["stop"] if hit_stop else (pos["target"] if hit_target else row["close"])
                        pnl = self._pnl(pos["side"], pos["entry"], exit_price, pos["stake"], pos["multiplier"])
                        trades.append(
                            {
                                "symbol": sym,
                                "side": pos["side"],
                                "entry_date": pos["entry_date"],
                                "exit_date": date,
                                "entry": pos["entry"],
                                "exit": exit_price,
                                "stake": pos["stake"],
                                "pnl": pnl,
                            }
                        )
                        self.risk.register_close(pnl)
                        del positions[sym]

                elif signal.action in (Action.BUY, Action.SELL) and not self.risk.halted:
                    side = "long" if signal.action == Action.BUY else "short"
                    stake, _, _ = self.risk.stake_and_limits(signal.price, signal.stop_price, signal.take_profit_price)
                    if stake > 0:
                        positions[sym] = {
                            "side": side,
                            "entry": signal.price,
                            "stop": signal.stop_price,
                            "target": signal.take_profit_price,
                            "stake": stake,
                            "multiplier": self.risk.multiplier,
                            "entry_date": date,
                        }
                        self.risk.register_open()

            unrealized = 0.0
            for sym, pos in positions.items():
                if date in prepared[sym].index:
                    price = prepared[sym].loc[date, "close"]
                    unrealized += self._pnl(pos["side"], pos["entry"], price, pos["stake"], pos["multiplier"])
            equity_points.append((date, self.risk.equity + unrealized))

        curve = pd.Series({d: v for d, v in equity_points}).sort_index()
        metrics = compute_cfd_metrics(curve, trades)
        return {"equity_curve": curve, "trades": trades, "metrics": metrics}

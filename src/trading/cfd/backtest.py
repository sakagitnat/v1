import pandas as pd

from trading.cfd.portfolio_risk import OpenRiskPosition, PortfolioRiskCeilings, check_new_position
from trading.cfd.risk import CfdRiskManager
from trading.config import settings
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
    resting in a market that can gap past them). This means the "no
    slippage" part of Revision 3 gap #6 (docs/ARCHITECTURE_AUDIT.md) was
    never actually a modeling gap for THIS product -- it's the correct
    behavior, not an optimistic simplification.

    Spread and overnight financing ARE real, unmodeled costs this class
    now supports via spread_pct/daily_financing_pct (both default 0.0,
    preserving every existing caller/test's exact-fill assertions unless
    explicitly opted in -- see scripts/research_cfd_strategy.py etc. for
    where real validation runs pass the configured, non-zero settings
    values). spread_pct is charged once per round trip at close
    (notional * spread_pct, deducted from that trade's own pnl) --
    modeling "crossing the spread" to open and close. daily_financing_pct
    is charged directly against equity for every full UTC calendar day a
    position stays open (notional * daily_financing_pct per day) --
    modeling the leveraged holding cost real Multipliers charge, which
    matters far more now that Revision 3's exit philosophy explicitly
    allows multi-hour/multi-day holds. Neither Deriv's actual live spread
    nor its actual financing rate is confirmed against real numbers here
    -- these are stated, reasonable placeholders (same status as the
    ADX/regime threshold defaults elsewhere in this project), not
    calibrated to live data. No separate commission line is modeled: no
    confirmed commission structure exists for this product beyond spread
    and financing, and this project never invents an unconfirmed number.

    Every new entry also passes trading.cfd.portfolio_risk.
    check_new_position() -- the same Portfolio Risk Governor
    trading.cfd.scheduler applies live (per-thesis, correlated,
    portfolio, and leverage ceilings), so a backtest across several
    symbols at once can't validate a result live trading's own risk
    ceilings would actually have rejected. ceilings defaults to the
    configured settings (same values live trading uses) if not given."""

    def __init__(
        self,
        strategy,
        starting_equity: float = 10_000.0,
        risk_per_trade: float = 0.01,
        max_open_positions: int = 3,
        max_daily_loss_pct: float = 0.03,
        multiplier: int = 20,
        ceilings: PortfolioRiskCeilings = None,
        spread_pct: float = 0.0,
        daily_financing_pct: float = 0.0,
    ):
        self.strategy = strategy
        self.risk = CfdRiskManager(
            equity=starting_equity,
            risk_per_trade=risk_per_trade,
            max_open_positions=max_open_positions,
            max_daily_loss_pct=max_daily_loss_pct,
            multiplier=multiplier,
        )
        self.ceilings = ceilings or PortfolioRiskCeilings(
            max_thesis_risk_pct=settings.cfd_max_thesis_risk_pct,
            max_correlated_risk_pct=settings.cfd_max_correlated_risk_pct,
            max_portfolio_risk_pct=settings.cfd_max_portfolio_risk_pct,
            max_exposure_multiple=settings.cfd_max_exposure_multiple,
        )
        self.spread_pct = spread_pct
        self.daily_financing_pct = daily_financing_pct

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
                if self.daily_financing_pct > 0:
                    for pos in positions.values():
                        self.risk.equity -= pos["stake"] * pos["multiplier"] * self.daily_financing_pct
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
                        spread_cost = pos["stake"] * pos["multiplier"] * self.spread_pct
                        pnl -= spread_cost
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
                                "spread_cost": round(spread_cost, 4),
                            }
                        )
                        self.risk.register_close(pnl)
                        del positions[sym]

                elif signal.action in (Action.BUY, Action.SELL) and not self.risk.halted:
                    side = "long" if signal.action == Action.BUY else "short"
                    stake, risk_amount, _ = self.risk.stake_and_limits(signal.price, signal.stop_price, signal.take_profit_price)
                    if stake > 0:
                        notional = stake * self.risk.multiplier
                        open_risk_positions = [
                            OpenRiskPosition(
                                contract_id=0, instrument=other_sym, side=pos["side"],
                                risk_amount=pos["risk_amount"], notional=pos["stake"] * pos["multiplier"],
                            )
                            for other_sym, pos in positions.items()
                        ]
                        rejection = check_new_position(
                            open_risk_positions, sym, side, risk_amount, notional, self.risk.equity, self.ceilings,
                        )
                        if rejection is None:
                            positions[sym] = {
                                "side": side,
                                "entry": signal.price,
                                "stop": signal.stop_price,
                                "target": signal.take_profit_price,
                                "stake": stake,
                                "risk_amount": risk_amount,
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

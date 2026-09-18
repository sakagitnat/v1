import numpy as np
import pandas as pd


def compute_metrics(equity_curve: pd.Series, trades: list[dict]) -> dict:
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
    years = max(len(equity_curve) / 252, 1e-9)
    cagr = (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1.0

    sharpe = 0.0
    if returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)

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

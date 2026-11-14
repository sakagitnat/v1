"""Performance Engine -- src/trading/cfd/performance.py

Computes the metrics docs/VISION.md's Performance Engine section requires
from the Trade Database (trading.cfd.trade_log.load_trades()): net
return, expectancy, profit factor, win rate, average win/loss, R
multiple, Sharpe, Sortino, Calmar, max drawdown, longest losing streak,
and breakdowns by strategy, regime, session, and side.

Every pnl-based metric is computed only over trades with a known pnl --
a trade closed externally with unattributed P&L (see scheduler.py's
reconciliation of contracts Deriv auto-closed between runs) is counted in
trade_count but excluded from every pnl-based average, never treated as
0.0. Coercing an unknown to zero would silently bias every average toward
zero for a case that just means "not priced yet," not "broke even."
"""
import pandas as pd


def _priced(trades: list[dict]) -> list[dict]:
    return [t for t in trades if t.get("pnl") is not None]


def _session_for_hour(hour: int) -> str:
    # Plain 6-hour UTC buckets, not named FX sessions (London/NY/Tokyo
    # session hours are themselves debatable and shift with DST) -- this
    # only needs to be a stable, honest grouping key.
    if 0 <= hour < 6:
        return "00-06 UTC"
    if 6 <= hour < 12:
        return "06-12 UTC"
    if 12 <= hour < 18:
        return "12-18 UTC"
    return "18-24 UTC"


def _equity_curve(priced: list[dict], starting_equity: float) -> pd.Series:
    """Anchors the curve at starting_equity before any trade's pnl is
    applied -- without this anchor point, a drawdown straight down from
    the very first trade would be invisible (there'd be no earlier, higher
    point for running_max to compare against)."""
    ordered = sorted(priced, key=lambda t: t["exit_time"])
    if not ordered:
        return pd.Series(dtype=float)
    anchor_time = pd.Timestamp(ordered[0].get("entry_time") or ordered[0]["exit_time"])
    equity = starting_equity
    points = [(anchor_time, equity)]
    for t in ordered:
        equity += t["pnl"]
        points.append((pd.Timestamp(t["exit_time"]), equity))
    return pd.Series({d: v for d, v in points}).sort_index()


def _drawdown_and_streak(priced: list[dict], starting_equity: float) -> tuple[float, int]:
    curve = _equity_curve(priced, starting_equity)
    max_drawdown_pct = 0.0
    if not curve.empty:
        running_max = curve.cummax()
        drawdown = curve / running_max - 1
        max_drawdown_pct = round(float(drawdown.min()) * 100, 2)

    longest_streak = streak = 0
    for t in sorted(priced, key=lambda t: t["exit_time"]):
        if t["pnl"] < 0:
            streak += 1
            longest_streak = max(longest_streak, streak)
        else:
            streak = 0
    return max_drawdown_pct, longest_streak


def _sharpe_sortino(priced: list[dict]) -> tuple[float, float]:
    """Per-trade Sharpe/Sortino (mean/std of trade pnl), not annualized --
    trades don't arrive on a fixed schedule the way daily bars do, so
    annualizing here would have to assume a trade frequency that isn't a
    settled fact yet this early in live trading. Revisit once there's
    enough live history to know the real trade cadence."""
    if len(priced) < 2:
        return 0.0, 0.0
    pnls = pd.Series([t["pnl"] for t in priced])
    sharpe = float(pnls.mean() / pnls.std()) if pnls.std() > 0 else 0.0
    downside = pnls[pnls < 0]
    sortino = float(pnls.mean() / downside.std()) if len(downside) > 1 and downside.std() > 0 else 0.0
    return round(sharpe, 3), round(sortino, 3)


def _basic_stats(priced: list[dict]) -> dict:
    if not priced:
        return {"trade_count": 0, "net_pnl": 0.0, "win_rate_pct": 0.0, "expectancy": 0.0}
    pnls = [t["pnl"] for t in priced]
    wins = [p for p in pnls if p > 0]
    return {
        "trade_count": len(priced),
        "net_pnl": round(sum(pnls), 2),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 2),
        "expectancy": round(sum(pnls) / len(pnls), 2),
    }


def _group_summary(priced: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for t in priced:
        groups.setdefault(t.get(key) or "unknown", []).append(t)
    return {name: _basic_stats(rows) for name, rows in groups.items()}


def _empty_result(trade_count: int, unattributed: int) -> dict:
    return {
        "trade_count": trade_count,
        "priced_trade_count": 0,
        "unattributed_trade_count": unattributed,
        "net_return": 0.0,
        "expectancy": 0.0,
        "profit_factor": None,
        "win_rate_pct": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "avg_r_multiple": None,
        "sharpe": 0.0,
        "sortino": 0.0,
        "calmar": None,
        "max_drawdown_pct": 0.0,
        "longest_losing_streak": 0,
        "exposure_pct": None,
        "by_strategy": {},
        "by_regime": {},
        "by_session": {},
        "by_side": {},
    }


def compute_performance(trades: list[dict], starting_equity: float = 100.0) -> dict:
    """trades: whatever trading.cfd.trade_log.load_trades() returns.
    starting_equity should be the virtual starting capital (see
    trading.cfd.capital / CFD_VIRTUAL_STARTING_CAPITAL) the trade log's
    pnl figures are already denominated in -- used here only to build an
    equity curve for drawdown/Calmar, never to re-derive pnl itself."""
    priced = _priced(trades)
    unattributed = len(trades) - len(priced)
    if not priced:
        return _empty_result(len(trades), unattributed)

    pnls = [t["pnl"] for t in priced]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net_return = sum(pnls)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    r_multiples = [t["pnl"] / t["risk_amount"] for t in priced if t.get("risk_amount")]

    max_dd_pct, longest_streak = _drawdown_and_streak(priced, starting_equity)
    sharpe, sortino = _sharpe_sortino(priced)

    calmar = None
    if max_dd_pct < 0 and starting_equity:
        total_return_pct = net_return / starting_equity * 100
        calmar = round(total_return_pct / abs(max_dd_pct), 3)

    exposure_pct = None
    holding_hours = [
        (pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 3600
        for t in priced
        if t.get("entry_time") and t.get("exit_time")
    ]
    if holding_hours:
        span_hours = (
            pd.Timestamp(max(t["exit_time"] for t in priced if t.get("exit_time")))
            - pd.Timestamp(min(t["entry_time"] for t in priced if t.get("entry_time")))
        ).total_seconds() / 3600
        if span_hours > 0:
            exposure_pct = round(sum(holding_hours) / span_hours * 100, 2)

    by_session_rows = [
        {**t, "_session": _session_for_hour(pd.Timestamp(t["entry_time"]).hour)}
        for t in priced
        if t.get("entry_time")
    ]

    return {
        "trade_count": len(trades),
        "priced_trade_count": len(priced),
        "unattributed_trade_count": unattributed,
        "net_return": round(net_return, 2),
        "expectancy": round(net_return / len(priced), 2),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "win_rate_pct": round(len(wins) / len(priced) * 100, 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "avg_r_multiple": round(sum(r_multiples) / len(r_multiples), 3) if r_multiples else None,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown_pct": max_dd_pct,
        "longest_losing_streak": longest_streak,
        "exposure_pct": exposure_pct,
        "by_strategy": _group_summary(priced, "strategy"),
        "by_regime": _group_summary(priced, "regime"),
        "by_session": _group_summary(by_session_rows, "_session"),
        "by_side": _group_summary(priced, "side"),
    }

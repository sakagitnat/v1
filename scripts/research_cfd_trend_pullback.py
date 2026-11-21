"""Validate TrendPullbackStrategy through TRAIN/TEST/walk-forward/Monte Carlo."""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading.cfd.backtest import CfdBacktestEngine
from trading.cfd.broker import DerivBroker
from trading.cfd.research_lab import evaluate_candidate, generate_candidate_params, register_if_passed
from trading.cfd.strategy_registry import list_all
from trading.cfd.trend_pullback import TrendPullbackStrategy
from trading.config import settings

from optimize_cfd_strategy import (
    MAX_DRAWDOWN_CAP, MIN_TRADES, TOP_N_TO_TEST, TRAIN_FRACTION,
    YFINANCE_INTERVAL_BY_GRANULARITY, calmar, fetch_history,
    fetch_history_yfinance, fmt, split,
)

STRATEGY_NAME="trend_pullback"
SUITED_REGIMES=["trending"]
PARAM_GRID={
    "fast_span":[15,20,30],
    "slow_span":[40,50,65],
    "adx_threshold":[18,22,25],
    "pullback_atr_tolerance":[0.25,0.5],
    "atr_stop_mult":[1.5,2.0],
    "atr_target_mult":[2.5,4.0],
}

def run_backtest_full(params,bars):
    engine=CfdBacktestEngine(
        strategy=TrendPullbackStrategy(**params),
        starting_equity=10_000.0,
        risk_per_trade=settings.cfd_risk_per_trade,
        max_open_positions=settings.cfd_max_open_positions,
        max_daily_loss_pct=settings.cfd_max_daily_loss_pct,
        spread_pct=settings.cfd_backtest_spread_pct,
        daily_financing_pct=settings.cfd_backtest_daily_financing_pct,
    )
    return engine.run(bars)

async def main(granularity_seconds:int, source:str):
    bars={}
    if source=="deriv":
        broker=DerivBroker()
        try:
            await broker.connect()
            for instrument in settings.cfd_instruments:
                bars[instrument]=await fetch_history(broker,instrument,granularity_seconds)
        finally:
            await broker.close()
    else:
        interval=YFINANCE_INTERVAL_BY_GRANULARITY.get(granularity_seconds,"1h")
        for instrument in settings.cfd_instruments:
            bars[instrument]=fetch_history_yfinance(instrument,interval)

    bars={k:v for k,v in bars.items() if not v.empty}
    if not bars:
        raise SystemExit("No history fetched.")
    train_bars,test_bars=split(bars)
    baseline_test=run_backtest_full({},test_bars)["metrics"]
    print(f"TRAIN={TRAIN_FRACTION:.0%}, TEST={1-TRAIN_FRACTION:.0%}")
    print(f"Baseline TEST: {fmt(baseline_test)}")

    candidates=generate_candidate_params(PARAM_GRID,filter_fn=lambda c:c["fast_span"]<c["slow_span"])
    ranked=[]
    for params in candidates:
        m=run_backtest_full(params,train_bars)["metrics"]
        if m["num_trades"]>=MIN_TRADES and m["cagr_pct"]>0 and m["max_drawdown_pct"]>=MAX_DRAWDOWN_CAP:
            ranked.append((params,m))
    ranked.sort(key=lambda x:calmar(x[1]),reverse=True)
    print(f"{len(ranked)}/{len(candidates)} cleared TRAIN gate.")
    if not ranked:
        print("NEGATIVE RESULT: no candidate cleared TRAIN gate.")
        return

    existing={e.version for e in list_all() if e.name==STRATEGY_NAME}
    next_v=max([int(v[1:]) for v in existing if v.startswith("v") and v[1:].isdigit()] or [0])+1
    passed=[]
    for params,train_m in ranked[:TOP_N_TO_TEST]:
        report=evaluate_candidate(run_backtest_full,train_bars,test_bars,params,baseline_test)
        print(f"Candidate {params}\n  TRAIN {fmt(train_m)}\n  TEST  {fmt(report.test_metrics)}")
        if not report.passed:
            print(f"  REJECTED: {report.reasons}")
            continue
        version=f"v{next_v}"; next_v+=1
        register_if_passed(STRATEGY_NAME,version,report,regimes=SUITED_REGIMES)
        passed.append((version,params,report))
        print(f"  PASSED -> {STRATEGY_NAME}@{version} VALIDATED")
    if not passed:
        print("NEGATIVE RESULT: no top candidate cleared full validation.")
    else:
        print("=== VALIDATED RESULTS ===")
        for version,params,report in passed:
            print(f"{STRATEGY_NAME}@{version}: {params}")
            print(f"  TRAIN {fmt(report.train_metrics)}")
            print(f"  TEST  {fmt(report.test_metrics)}")
            print(f"  walk-forward consistency={report.walk_forward['consistency_pct']}%")
            print(f"  Monte Carlo ruin={report.monte_carlo['ruin_probability_pct']}%")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--granularity",type=int,default=3600)
    p.add_argument("--source",choices=["deriv","yfinance"],default="yfinance")
    a=p.parse_args()
    asyncio.run(main(a.granularity,a.source))

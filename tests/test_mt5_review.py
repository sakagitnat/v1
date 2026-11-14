import importlib.util
from pathlib import Path

import pandas as pd

_spec = importlib.util.spec_from_file_location("mt5_review", Path(__file__).resolve().parents[1] / "scripts" / "mt5_review.py")
review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(review)


def _group(pnls):
    return pd.DataFrame({"net": pnls})


def test_stats_profit_factor_and_drawdown():
    s = review._stats(_group([10, -5, -5, 20]), start_balance=100)
    assert s["n"] == 4 and s["win"] == 50.0
    assert s["net"] == 20 and s["pf"] == 3.0          # 30 gross profit / 10 gross loss
    assert round(s["dd_pct"], 1) == round(10 / 110 * 100, 1)  # 110 peak -> 100 trough


def test_verdict_needs_enough_trades_before_judging():
    assert "keep collecting" in review._verdict(5, 0.1, 90.0, 1.3)


def test_verdict_pauses_on_bad_pf_or_drawdown():
    assert review._verdict(40, 0.5, 10.0, 1.3).startswith("PAUSE")
    assert review._verdict(40, 1.5, 55.0, 1.3).startswith("PAUSE")


def test_verdict_on_track_vs_ahead():
    assert review._verdict(40, 1.0, 10.0, 1.3).startswith("on track")
    assert review._verdict(40, 1.4, 10.0, 1.3).startswith("ahead")

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from diagnose_cfd_regime import Episode, _episodes, _pct, _percentile, _session


def test_episodes_splits_contiguous_runs():
    labels = np.array(["ranging", "ranging", "trending", "trending", "trending", "ranging"])
    episodes = _episodes(labels)
    assert [(e.label, e.start_pos, e.end_pos) for e in episodes] == [
        ("ranging", 0, 1),
        ("trending", 2, 4),
        ("ranging", 5, 5),
    ]


def test_episode_length_is_inclusive():
    assert Episode(label="ranging", start_pos=2, end_pos=5).length == 4
    assert Episode(label="ranging", start_pos=0, end_pos=0).length == 1


def test_episodes_handles_empty_input():
    assert _episodes(np.array([])) == []


def test_episodes_handles_a_single_run():
    labels = np.array(["trending"] * 5)
    episodes = _episodes(labels)
    assert len(episodes) == 1
    assert episodes[0].length == 5


def test_pct_computes_a_rounded_percentage():
    assert _pct(25, 100) == 25.0
    assert _pct(1, 3) == 33.3


def test_pct_of_empty_total_is_zero_not_a_division_error():
    assert _pct(0, 0) == 0.0


def test_percentile_of_empty_list_is_nan():
    import math

    assert math.isnan(_percentile([], 90))


def test_percentile_matches_numpy():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile(values, 50) == 3.0


def test_session_buckets_cover_all_24_hours_with_no_gaps():
    seen = {_session(hour) for hour in range(24)}
    assert seen == {"Asian", "London", "NY", "Late"}


def test_session_boundaries():
    assert _session(0) == "Asian"
    assert _session(6) == "Asian"
    assert _session(7) == "London"
    assert _session(12) == "London"
    assert _session(13) == "NY"
    assert _session(20) == "NY"
    assert _session(21) == "Late"
    assert _session(23) == "Late"

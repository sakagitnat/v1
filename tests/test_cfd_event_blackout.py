from datetime import datetime, timedelta, timezone

import pytest

from trading.cfd.event_blackout import EconomicEvent, in_blackout_window

FED = EconomicEvent(name="FOMC rate decision", scheduled_at=datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc), impact="high")
NFP_MEDIUM = EconomicEvent(name="minor labor release", scheduled_at=datetime(2026, 9, 20, 12, 30, tzinfo=timezone.utc), impact="medium")


def test_outside_any_window_is_not_blacked_out():
    now = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    assert in_blackout_window(now, [FED]) is None


def test_inside_default_window_before_event_is_blacked_out():
    now = FED.scheduled_at - timedelta(minutes=10)
    assert in_blackout_window(now, [FED]) is FED


def test_inside_default_window_after_event_is_blacked_out():
    now = FED.scheduled_at + timedelta(minutes=10)
    assert in_blackout_window(now, [FED]) is FED


def test_exactly_at_event_time_is_blacked_out():
    assert in_blackout_window(FED.scheduled_at, [FED]) is FED


def test_just_outside_window_boundary_is_not_blacked_out():
    now = FED.scheduled_at - timedelta(minutes=16)
    assert in_blackout_window(now, [FED], window_before_minutes=15) is None


def test_exactly_at_window_boundary_is_blacked_out():
    now = FED.scheduled_at - timedelta(minutes=15)
    assert in_blackout_window(now, [FED], window_before_minutes=15) is FED


def test_custom_window_widths_are_respected():
    now = FED.scheduled_at + timedelta(minutes=45)
    assert in_blackout_window(now, [FED], window_after_minutes=30) is None
    assert in_blackout_window(now, [FED], window_after_minutes=60) is FED


def test_medium_impact_event_does_not_block_with_default_min_impact():
    now = NFP_MEDIUM.scheduled_at
    assert in_blackout_window(now, [NFP_MEDIUM]) is None


def test_medium_impact_event_blocks_when_min_impact_lowered():
    now = NFP_MEDIUM.scheduled_at
    assert in_blackout_window(now, [NFP_MEDIUM], min_impact="medium") is NFP_MEDIUM


def test_empty_event_list_is_never_blacked_out():
    now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    assert in_blackout_window(now, []) is None


def test_returns_the_first_matching_event_when_windows_overlap():
    now = FED.scheduled_at
    overlapping = EconomicEvent(name="overlapping high-impact event", scheduled_at=FED.scheduled_at + timedelta(minutes=5), impact="high")
    assert in_blackout_window(now, [FED, overlapping]) is FED


def test_invalid_min_impact_raises():
    with pytest.raises(ValueError):
        in_blackout_window(FED.scheduled_at, [FED], min_impact="extreme")

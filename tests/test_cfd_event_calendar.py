from datetime import datetime, timezone
from trading.cfd.event_calendar import EVENTS, SNAPSHOT_VERSION, SOURCES
from trading.cfd.event_blackout import in_blackout_window

def test_official_calendar_snapshot_has_sources_and_version():
    assert SNAPSHOT_VERSION == "2026-09-21"
    assert "bls.gov" in SOURCES["BLS"]
    assert "federalreserve.gov" in SOURCES["FOMC"]

def test_nfp_and_cpi_are_utc_aligned():
    assert EVENTS[0].scheduled_at == datetime(2026, 10, 2, 12, 30, tzinfo=timezone.utc)
    assert EVENTS[1].scheduled_at == datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc)

def test_event_window_detects_nfp():
    now = datetime(2026, 10, 2, 12, 25, tzinfo=timezone.utc)
    assert in_blackout_window(now, EVENTS).name.startswith("US Employment")

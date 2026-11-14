from datetime import datetime, timezone
from pathlib import Path

from scripts.cfd_runner_health import assess, expected_market_window


def dt(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_expected_market_window_covers_sunday_open_and_daily_break():
    assert expected_market_window(dt(2026, 9, 20, 22, 9)) is False
    assert expected_market_window(dt(2026, 9, 20, 22, 10)) is True
    assert expected_market_window(dt(2026, 9, 21, 20, 58)) is True
    assert expected_market_window(dt(2026, 9, 21, 21, 30)) is False
    assert expected_market_window(dt(2026, 9, 21, 22, 5)) is True


def test_expected_market_window_closes_friday_and_saturday():
    assert expected_market_window(dt(2026, 9, 25, 20, 45)) is True
    assert expected_market_window(dt(2026, 9, 25, 20, 46)) is False
    assert expected_market_window(dt(2026, 9, 26, 12, 0)) is False


def test_missing_heartbeat_is_stale_only_when_market_expected(tmp_path: Path):
    path = tmp_path / "heartbeat.json"
    open_result = assess(dt(2026, 9, 21, 10, 0), 40, path)
    assert open_result["healthy"] is False
    assert open_result["reason"] == "heartbeat_missing"

    closed_result = assess(dt(2026, 9, 26, 10, 0), 40, path)
    assert closed_result["healthy"] is True
    assert closed_result["reason"] == "outside_expected_market_window"


def test_fresh_success_heartbeat_is_healthy(tmp_path: Path):
    path = tmp_path / "heartbeat.json"
    path.write_text(
        '{"status":"success","last_update_at":"2026-09-21T09:45:00+00:00","run_id":"123"}'
    )
    result = assess(dt(2026, 9, 21, 10, 0), 40, path)
    assert result["healthy"] is True
    assert result["reason"] == "fresh"


def test_failure_or_stale_heartbeat_requires_recovery(tmp_path: Path):
    failed = tmp_path / "failed.json"
    failed.write_text(
        '{"status":"failure","last_update_at":"2026-09-21T09:59:00+00:00","run_id":"1"}'
    )
    assert assess(dt(2026, 9, 21, 10, 0), 40, failed)["reason"] == "last_run_failed"

    stale = tmp_path / "stale.json"
    stale.write_text(
        '{"status":"success","last_update_at":"2026-09-21T08:00:00+00:00","run_id":"2"}'
    )
    assert assess(dt(2026, 9, 21, 10, 0), 40, stale)["reason"] == "heartbeat_stale"

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from scripts import run_cfd_service as service
from trading.cfd import scheduler, state


def test_failed_cycle_is_saved_and_not_retried(monkeypatch):
    events = []
    monkeypatch.setattr(service, "mark", events.append)
    monkeypatch.setattr(service, "checkpoint", lambda: events.append("checkpoint"))
    def fail(args):
        events.append("broker")
        raise TimeoutError()
    monkeypatch.setattr(service, "command", fail)
    with pytest.raises(TimeoutError):
        service.cycle()
    assert events == ["started", "broker", "failure", "checkpoint"]


def test_success_is_checkpointed_before_return(monkeypatch):
    events = []
    monkeypatch.setattr(service, "mark", events.append)
    monkeypatch.setattr(service, "checkpoint", lambda: events.append("checkpoint"))
    monkeypatch.setattr(service, "command", lambda args: events.append(args[-1]))
    service.cycle(False)
    assert events == ["started", "scripts/run_cfd_quota.py", "success", "checkpoint"]


def test_expired_probe_only_closes_owned_demo_and_retains_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "state.json")
    meta = dict(experimental=True, broker_managed_only=True, entry_timeframe="M5",
                entry_time="2026-09-21T05:55:45+00:00")
    state.record_open_trade(1, meta)
    state.record_open_trade(2, dict(meta, experimental=False))
    state.record_open_trade(3, dict(meta, quota_window=12))
    broker = AsyncMock()
    broker.open_contract_ids.side_effect = [{1, 2, 3}, {2, 3}]
    asyncio.run(scheduler.close_overdue_demo_probes(broker, "real"))
    broker.close_position.assert_not_awaited()
    asyncio.run(scheduler.close_overdue_demo_probes(broker, "demo", datetime(2026, 9, 24, tzinfo=timezone.utc)))
    broker.close_position.assert_awaited_once_with(1)
    assert state.list_open_trades()["1"]["exit_requested_reason"] == "legacy_demo_probe_max_holding_time"
    assert len(state.list_open_trades()) == 3  # settlement reconciliation owns removal



def test_checkpoint_rotates_before_staging(monkeypatch):
    from types import SimpleNamespace

    events = []
    monkeypatch.setattr(service, "rotate_lab_observations",
                        lambda: events.append("rotate") or {"rotated": True})
    monkeypatch.setattr(service, "command",
                        lambda args, timeout=240: events.append(args[:3]))
    monkeypatch.setattr(service.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0))

    service.checkpoint()
    assert events[0] == "rotate"
    assert events[1] == ["git", "add", "-u"]


def test_lab_rotation_preserves_jsonl_bytes_and_bounds_chunks(tmp_path, monkeypatch):
    from scripts import rotate_cfd_lab_observations as rotation

    monkeypatch.setattr(rotation, "ROTATE_AT", 128)
    monkeypatch.setattr(rotation, "CHUNK_MAX", 64)
    active = tmp_path / "cfd_lab_observations.jsonl"
    original = b"".join((f'{{"n":{n}}}\n').encode() for n in range(40))
    active.write_bytes(original)

    result = rotation.rotate(active)
    assert result["rotated"] is True
    archives = sorted(tmp_path.glob("cfd_lab_observations_archive_*.jsonl"))
    assert archives
    assert all(p.stat().st_size <= 64 for p in archives)
    assert b"".join(p.read_bytes() for p in archives) + active.read_bytes() == original
    assert rotation.rotate(active) == {"rotated": False}

import json

import pytest

from scripts import cfd_scheduler_heartbeat as hb


def test_trading_workflow_can_write_heartbeat(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.json"
    monkeypatch.setenv("GITHUB_WORKFLOW", "CFD Trading (Deriv)")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("CFD_RUNTIME_REF", "gpt/autonomous-demo-runner")

    result = hb.mark("success", path=path)

    assert result["workflow"] == "CFD Trading (Deriv)"
    assert result["run_id"] == "123"
    assert json.loads(path.read_text())["status"] == "success"


def test_non_trading_workflow_cannot_overwrite_authoritative_heartbeat(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps({"workflow": "CFD Trading (Deriv)", "status": "success"}))
    before = path.read_text()

    monkeypatch.setenv("GITHUB_WORKFLOW", "GPT Handoff CI")

    with pytest.raises(RuntimeError, match="refusing to write scheduler heartbeat"):
        hb.mark("success", path=path)

    assert path.read_text() == before

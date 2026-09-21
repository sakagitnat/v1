import json

from scripts.run_cfd_trading import run_bridge


def test_run_bridge_reports_ok_with_instrument_summary(monkeypatch, capsys):
    async def fake_run_once(command_id):
        assert command_id == "123e4567-e89b-12d3-a456-426614174000"
        return [{"instrument": "frxXAUUSD", "outcome": "TRADE", "reason": "long ema_crossover@v1 (1 leg(s))"}]

    monkeypatch.setattr("scripts.run_cfd_trading.run_once", fake_run_once)
    monkeypatch.setenv("GITHUB_RUN_ID", "999")

    result = run_bridge("123e4567-e89b-12d3-a456-426614174000")

    assert result["status"] == "OK"
    assert result["run_id"] == "999"
    assert result["instruments"][0]["outcome"] == "TRADE"

    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("BRIDGE_RESULT_JSON="))
    printed = json.loads(line[len("BRIDGE_RESULT_JSON="):])
    assert printed == result


def test_run_bridge_reports_error_without_leaking_the_exception_message(monkeypatch, capsys):
    async def fake_run_once(command_id):
        raise ConnectionError("token=super-secret-value")

    monkeypatch.setattr("scripts.run_cfd_trading.run_once", fake_run_once)

    result = run_bridge("123e4567-e89b-12d3-a456-426614174000")

    assert result["status"] == "ERROR"
    assert result["error"] == "ConnectionError"
    assert result["instruments"] == []

    out = capsys.readouterr().out
    assert "super-secret-value" not in out

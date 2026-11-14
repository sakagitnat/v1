from pathlib import Path

import pytest

from scripts.cfd_ai_bridge import BridgeCommandError, format_audit_comment, parse_command, reserve


VALID = "AI_EXECUTE_DEMO command_id=123e4567-e89b-12d3-a456-426614174000 intent=evaluate"


def test_parse_accepts_exact_authorized_command():
    command_id, intent = parse_command(VALID, "sakagitnat", 5)
    assert command_id == "123e4567-e89b-12d3-a456-426614174000"
    assert intent == "evaluate"


@pytest.mark.parametrize(
    "body,actor,issue",
    [
        (VALID, "someone-else", 5),
        (VALID, "sakagitnat", 4),
        (VALID + " instrument=frxXAUUSD", "sakagitnat", 5),
        ("AI_EXECUTE_DEMO intent=evaluate", "sakagitnat", 5),
        ("AI_EXECUTE_DEMO command_id=not-a-uuid intent=evaluate", "sakagitnat", 5),
        ("AI_EXECUTE_DEMO command_id=123e4567-e89b-12d3-a456-426614174000 intent=enter", "sakagitnat", 5),
    ],
)
def test_parse_fails_closed(body, actor, issue):
    with pytest.raises(BridgeCommandError):
        parse_command(body, actor, issue)


def test_reserve_rejects_duplicate(tmp_path: Path):
    path = tmp_path / "commands.json"
    cid = "123e4567-e89b-12d3-a456-426614174000"
    reserve(cid, "sakagitnat", "evaluate", path)
    with pytest.raises(BridgeCommandError):
        reserve(cid, "sakagitnat", "evaluate", path)


def test_format_audit_comment_lists_each_instrument_outcome():
    result = {
        "command_id": VALID.split("command_id=")[1].split()[0],
        "run_id": "12345",
        "status": "OK",
        "instruments": [
            {"instrument": "frxXAUUSD", "outcome": "TRADE", "reason": "long ema_crossover@v1 (1 leg(s))"},
            {"instrument": "frxEURUSD", "outcome": "NO_TRADE", "reason": "regime=RANGING, no ACTIVE strategy suited to it with an available slot"},
        ],
    }
    body = format_audit_comment(result)
    assert "status: OK" in body
    assert "run: 12345" in body
    assert "frxXAUUSD: TRADE" in body
    assert "frxEURUSD: NO_TRADE" in body


def test_format_audit_comment_reports_error_without_the_exception_message():
    result = {"command_id": "123e4567-e89b-12d3-a456-426614174000", "status": "ERROR", "error": "ConnectionError", "instruments": []}
    body = format_audit_comment(result)
    assert "status: ERROR" in body
    assert "error: ConnectionError" in body


def test_format_audit_comment_handles_no_instruments_evaluated():
    result = {"command_id": "123e4567-e89b-12d3-a456-426614174000", "status": "OK", "instruments": []}
    body = format_audit_comment(result)
    assert "(no instruments evaluated)" in body

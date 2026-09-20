from pathlib import Path

import pytest

from scripts.cfd_ai_bridge import BridgeCommandError, parse_command, reserve


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

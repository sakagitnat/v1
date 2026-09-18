import json
from pathlib import Path

_STATE_PATH = Path(__file__).resolve().parents[3] / "state" / "bot_state.json"


def load_state() -> dict:
    if not _STATE_PATH.exists():
        return {"paused": False}
    return json.loads(_STATE_PATH.read_text())


def set_paused(paused: bool) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps({"paused": paused}, indent=2) + "\n")

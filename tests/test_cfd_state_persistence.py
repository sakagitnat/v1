"""Reproduce the unstaged observation file that broke production persistence."""
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("workflow", ["cfd-trading.yml"])
def test_persistence_stages_observations_and_new_ledgers(tmp_path, workflow):
    source = Path(".github/workflows", workflow).read_text()
    start = source.index("          git add -u -- state")
    end = source.index("          if ! git diff", start)
    script = "\n".join(line[10:] for line in source[start:end].splitlines())
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout
    git("init", "-q")
    git("config", "user.name", "test")
    git("config", "user.email", "test@example.invalid")
    state = tmp_path / "state"
    state.mkdir()
    for name in ("cfd_bot_state.json", "cfd_lab_observations.jsonl"):
        (state / name).write_text("{}\n")
    git("add", "state")
    git("commit", "-qm", "baseline")
    (state / "cfd_bot_state.json").write_text('{"updated": true}\n')
    (state / "cfd_lab_observations.jsonl").write_text('{"new_observation": true}\n')
    (state / "cfd_virtual_account_ruin_log.jsonl").write_text("{}\n")
    subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path, check=True)
    assert not git("diff", "--name-only")  # previously the lab file stayed dirty
    assert len(git("diff", "--cached", "--name-only").splitlines()) == 3
    assert "actions/upload-artifact@v4" in source

"""Bounded Actions service; checkpoint every cycle and stop on any ambiguity.

Hosted Actions scheduling remains best effort. This reduces intra-run gaps;
it is not a replacement for a persistent host with a transactional database.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.cfd_scheduler_heartbeat import mark


def command(args, timeout=240):
    subprocess.run(args, cwd=ROOT, check=True, timeout=timeout)


def checkpoint():
    command(["git", "add", "-u", "--", "state"])
    files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "state").glob("cfd_*.json*"))
    if files:
        command(["git", "add", "--", *files])
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode
    if changed not in (0, 1):
        raise RuntimeError("Unable to inspect checkpoint")
    if changed:
        command(["git", "commit", "-m", "Checkpoint CFD demo service cycle"])
        command(["git", "pull", "--rebase", "origin", "gpt/autonomous-demo-runner"])
        command(["git", "push", "origin", "HEAD:gpt/autonomous-demo-runner"])


def cycle(run_scheduler=True):
    mark("started")
    try:
        # Exit/deadline management must not depend on the research scheduler.
        command([sys.executable, "scripts/run_cfd_quota.py"])
        if run_scheduler:
            command([sys.executable, "scripts/run_cfd_trading.py"])
    except BaseException:
        mark("failure")
        checkpoint()
        raise
    mark("success")
    checkpoint()  # no next broker operation unless remote state was saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.minutes <= 300:
        raise ValueError("Service duration must be 1..300 minutes")
    command(["git", "config", "user.name", "trading-bot"])
    command(["git", "config", "user.email", "actions@github.com"])
    deadline = time.monotonic() + args.minutes * 60
    index = 0
    while time.monotonic() < deadline:
        started = time.monotonic()
        cycle(run_scheduler=index % 5 == 0)
        print(f"CFD_SERVICE_CYCLE={index} persisted", flush=True)
        index += 1
        time.sleep(max(0, min(60 - (time.monotonic()-started), deadline-time.monotonic())))


if __name__ == "__main__":
    main()

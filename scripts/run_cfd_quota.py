"""Run bounded demo quota evaluation once; scheduler owns the repetition."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trading.cfd.quota import run_quotas

if __name__ == "__main__":
    asyncio.run(run_quotas())

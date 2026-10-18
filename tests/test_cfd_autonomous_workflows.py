from pathlib import Path

TRADING = Path(".github/workflows/cfd-trading.yml").read_text()
WATCHDOG = Path(".github/workflows/cfd-trading-watchdog.yml").read_text()


def test_service_has_single_writer_and_demo_guard():
    assert "group: cfd-trading" in TRADING
    assert "cancel-in-progress: false" in TRADING
    assert 'CFD_ALLOW_LIVE_TRADING: "false"' in TRADING
    assert "python scripts/run_cfd_service.py --minutes 180" in TRADING
    assert "if: always()" in TRADING
    assert "Archive runtime state" in TRADING


def test_watchdog_dispatches_instead_of_ineffective_token_push():
    assert "actions: write" in WATCHDOG
    assert "gh workflow run cfd-trading.yml" in WATCHDOG
    assert "gh run list" in WATCHDOG
    assert "git push" not in WATCHDOG
    assert "scripts/run_cfd_trading.py" not in WATCHDOG
    assert "if: steps.health.outcome == 'failure'" in WATCHDOG

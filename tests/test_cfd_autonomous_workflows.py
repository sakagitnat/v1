from pathlib import Path

TRADING = Path(".github/workflows/cfd-trading.yml").read_text()
WATCHDOG = Path(".github/workflows/cfd-trading-watchdog.yml").read_text()


def test_trading_and_watchdog_share_concurrency_group():
    assert "group: cfd-trading" in TRADING
    assert "group: cfd-trading" in WATCHDOG
    assert "cancel-in-progress: false" in TRADING
    assert "cancel-in-progress: false" in WATCHDOG


def test_all_execution_paths_are_demo_only():
    assert 'CFD_ALLOW_LIVE_TRADING: "false"' in TRADING
    assert 'CFD_ALLOW_LIVE_TRADING: "false"' in WATCHDOG


def test_schedule_covers_sunday_open_and_avoids_old_weekday_only_shape():
    assert '15,30,45 22 * * 0' in TRADING
    assert '*/15 23 * * 0' in TRADING
    assert '*/15 * * * 1-5' not in TRADING


def test_failed_scheduler_still_persists_state_and_heartbeat():
    assert "Persist scheduler state and heartbeat" in TRADING
    assert "if: always()" in TRADING
    assert "state/cfd_scheduler_heartbeat.json" in TRADING


def test_watchdog_only_recovers_after_failed_health_check():
    assert "continue-on-error: true" in WATCHDOG
    assert "if: steps.health.outcome == 'failure'" in WATCHDOG
    assert "python scripts/run_cfd_trading.py" in WATCHDOG


def test_runtime_ref_is_explicit_and_same_for_both_workflows():
    needle = "CFD_RUNTIME_REF: gpt/autonomous-demo-runner"
    assert needle in TRADING
    assert needle in WATCHDOG
    assert "ref: gpt/autonomous-demo-runner" in TRADING
    assert "ref: gpt/autonomous-demo-runner" in WATCHDOG

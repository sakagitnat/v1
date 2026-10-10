from datetime import datetime, timezone

from trading.cfd import decision_log


def test_decision_records_non_event_shadow_context(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_log, "_PATH", tmp_path / "decisions.jsonl")
    row = decision_log.record_decision("frxXAUUSD", "NO_TRADE", "test")
    context = row["context"]
    assert context["event_calendar_available"] is True
    assert "event_calendar_version" in context
    assert isinstance(context["event_blackout_shadow"], bool)
    assert "event_name" in context


def test_explicit_context_is_preserved_verbatim(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_log, "_PATH", tmp_path / "decisions.jsonl")
    supplied = {"experiment": "fixture", "event_blackout_shadow": True}
    row = decision_log.record_decision("frxEURUSD", "REJECTED", "test", context=supplied)
    assert row["context"] == supplied
    assert decision_log.load_decisions()[0]["context"] == supplied


def test_shadow_context_failure_is_unknown_not_false(monkeypatch):
    # The helper is intentionally fail-open for execution but fail-honest for
    # telemetry: unavailable data must never be mislabeled as "no event".
    import trading.cfd.event_blackout as blackout
    monkeypatch.setattr(blackout, "in_blackout_window", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    context = decision_log._shadow_context(datetime.now(timezone.utc))
    assert context["event_calendar_available"] is False
    assert context["event_blackout_shadow"] is None
    assert context["event_context_error"] == "RuntimeError"

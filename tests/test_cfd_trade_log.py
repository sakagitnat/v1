import json

from trading.cfd.trade_log import TradeRecord, load_trades, record_trade


def _record(contract_id=1, pnl=5.0):
    return TradeRecord(
        contract_id=contract_id,
        instrument="frxXAUUSD",
        strategy="ema_crossover",
        side="long",
        entry_time="2026-01-01T00:00:00+00:00",
        exit_time="2026-01-01T01:00:00+00:00",
        entry_price=2000.0,
        stake=10.0,
        risk_amount=1.0,
        exit_price=2010.0,
        pnl=pnl,
        equity_before=100.0,
        equity_after=None if pnl is None else 100.0 + pnl,
        exit_reason="signal_exit: test",
    )


def test_load_trades_returns_empty_list_when_file_missing(tmp_path):
    assert load_trades(tmp_path / "does_not_exist.jsonl") == []


def test_record_then_load_roundtrips(tmp_path, monkeypatch):
    from trading.cfd import trade_log

    path = tmp_path / "cfd_trades.jsonl"
    monkeypatch.setattr(trade_log, "_LOG_PATH", path)

    record_trade(_record(contract_id=1, pnl=5.0))
    record_trade(_record(contract_id=2, pnl=-3.0))

    trades = load_trades()
    assert len(trades) == 2
    assert trades[0]["contract_id"] == 1
    assert trades[0]["pnl"] == 5.0
    assert trades[1]["contract_id"] == 2
    assert trades[1]["pnl"] == -3.0


def test_each_line_is_independently_valid_json(tmp_path, monkeypatch):
    from trading.cfd import trade_log

    path = tmp_path / "cfd_trades.jsonl"
    monkeypatch.setattr(trade_log, "_LOG_PATH", path)
    record_trade(_record())

    lines = path.read_text().splitlines()
    assert len(lines) == 1
    json.loads(lines[0])  # must not raise


def test_unattributed_pnl_round_trips_as_null():
    record = _record(pnl=None)
    record.equity_after = None
    import dataclasses

    d = dataclasses.asdict(record)
    assert d["pnl"] is None

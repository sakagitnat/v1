"""Failure-injection tests; no network or broker credentials required."""
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
import requests

from trading.cfd.broker import DerivBroker
from trading.config import settings


def response(data=None, status=200):
    result = Mock(status_code=status)
    result.json.return_value = data
    return result


@pytest.fixture
def broker(monkeypatch):
    monkeypatch.setattr(settings, "deriv_api_token", "test-token")
    monkeypatch.setattr(settings, "cfd_allow_live_trading", False)
    return DerivBroker()


def test_otp_reset_recovers_without_order_submission(broker):
    demo = {"account_id": "demo-test", "account_type": "demo"}
    accounts = response({"data": [{"account_id": "real-test", "account_type": "real"}, demo]})
    otp = response({"data": {"url": "wss://example.invalid/otp"}})
    ws = AsyncMock()
    with patch("requests.request", side_effect=[accounts, requests.exceptions.ConnectionError("reset"), otp]) as http, patch("asyncio.sleep", new_callable=AsyncMock), patch("websockets.connect", new_callable=AsyncMock, return_value=ws):
        assert asyncio.run(broker.connect()) == demo
    assert [c.args[0] for c in http.call_args_list] == ["GET", "POST", "POST"]
    assert all(c.kwargs["timeout"] == (5, 15) for c in http.call_args_list)
    assert all(c.kwargs["allow_redirects"] is False for c in http.call_args_list)
    assert "/accounts/demo-test/otp" in http.call_args_list[-1].args[1]
    ws.send.assert_not_called()


def test_exhausted_transport_is_bounded_and_redacted(broker):
    with patch("requests.request", side_effect=requests.exceptions.Timeout("secret-token")) as http, patch("asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(RuntimeError, match="after 3 attempts") as exc:
            asyncio.run(broker.connect())
    assert http.call_count == 3
    assert sleep.await_count == 2
    assert "secret-token" not in str(exc.value)


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_http_errors_do_not_retry_or_leak_body(broker, status):
    resp = response(status=status)
    resp.text = "secret-token"
    with patch("requests.request", return_value=resp) as http:
        with pytest.raises(RuntimeError, match=f"HTTP {status}") as exc:
            asyncio.run(broker.connect())
    assert http.call_count == 1
    assert "secret-token" not in str(exc.value)
    resp.close.assert_called_once()


def test_demo_mode_never_falls_back_to_real(broker):
    accounts = response({"data": [{"account_id": "real-test", "account_type": "real"}]})
    with patch("requests.request", return_value=accounts) as http, patch("websockets.connect", new_callable=AsyncMock) as connect:
        with pytest.raises(RuntimeError, match="no DEMO account"):
            asyncio.run(broker.connect())
    assert http.call_count == 1
    connect.assert_not_called()


def test_ambiguous_buy_is_never_retransmitted(broker):
    broker._ws = AsyncMock()
    broker._ws.recv.side_effect = TimeoutError("ambiguous buy result")
    with pytest.raises(TimeoutError):
        asyncio.run(broker._request({"buy": "proposal-test", "price": 1}))
    assert broker._ws.send.await_count == 1


def test_settlement_reads_profit_for_the_specific_closed_contract(broker):
    broker._request = AsyncMock(return_value={"proposal_open_contract": {
        "contract_id": 42, "currency": "USD", "is_sold": 1, "profit": "-1.25"}})
    assert asyncio.run(broker.settled_profit(42)) == -1.25
    broker._request.assert_awaited_once_with({"proposal_open_contract": 1, "contract_id": 42})


@pytest.mark.parametrize("override", [
    {"contract_id": 99}, {"is_sold": 0}, {"currency": "EUR"},
    {"profit": None}, {"profit": "NaN"}, {"profit": "inf"}, {"profit": True},
])
def test_settlement_rejects_unconfirmed_or_invalid_data(broker, override):
    data = {"contract_id": 42, "currency": "USD", "is_sold": 1, "profit": 1}
    data.update(override)
    broker._request = AsyncMock(return_value={"proposal_open_contract": data})
    with pytest.raises(RuntimeError):
        asyncio.run(broker.settled_profit(42))

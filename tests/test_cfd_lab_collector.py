import asyncio
from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest

from trading.cfd import lab_collector, state, virtual_accounts
from trading.cfd.breakout import DonchianBreakoutStrategy
from trading.cfd.lab_collector import _strategy_for_tag, collect_lab_observations
from trading.cfd.mean_reversion import MeanReversionStrategy
from trading.cfd.strategy import EmaCrossoverStrategy


def test_breakout_tag_maps_to_donchian_breakout():
    assert isinstance(_strategy_for_tag("donchian_breakout@v2"), DonchianBreakoutStrategy)


def test_meanrev_tag_maps_to_mean_reversion():
    assert isinstance(_strategy_for_tag("mean_reversion@v1"), MeanReversionStrategy)


def test_ema_crossover_tag_maps_to_ema_crossover():
    assert isinstance(_strategy_for_tag("ema_crossover@v1"), EmaCrossoverStrategy)


def test_family_trend_and_hr20_trend_map_to_ema_crossover():
    assert isinstance(_strategy_for_tag("family_trend@v0"), EmaCrossoverStrategy)
    assert isinstance(_strategy_for_tag("hr20_trend@v0"), EmaCrossoverStrategy)


def test_unmapped_tags_return_none_instead_of_silently_defaulting_to_ema():
    for tag in (
        "momentum_research@v0",
        "hybrid_balanced@v0",
        "hybrid_adaptive@v0",
        "hybrid_aggressive@v0",
        "main_control@v0",
        "main_balanced@v0",
        "main_adaptive@v0",
        "main_challenger@v0",
        "family_momentum@v0",
        "hr20_momentum@v0",
        "news_momentum@v0",
        "news_control@v0",
        None,
        "",
    ):
        assert _strategy_for_tag(tag) is None


def _bars(n=200):
    return pd.DataFrame(
        {"open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n, "close": [100.0] * n},
        index=pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"),
    )


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "cfd_bot_state.json")
    monkeypatch.setattr(lab_collector, "LAB_LOG_PATH", tmp_path / "cfd_lab_observations.jsonl")


# 2026-09-26: crypto trades 24/7, unlike the forex/gold instruments
# CFD_INSTRUMENTS actually holds -- crypto_btc_h1/crypto_eth_h1 declare
# their own `instruments` override precisely so they never depend on (or
# widen) that global list. These tests are the regression guard for that:
# a crypto spec must be scanned regardless of what CFD_INSTRUMENTS holds,
# and an ordinary (override-less) spec must keep scanning CFD_INSTRUMENTS
# exactly as before -- neither should ever leak into the other's symbols.

def test_crypto_specs_are_scanned_even_when_absent_from_cfd_instruments():
    broker = Mock()
    broker.get_candles = AsyncMock(return_value=_bars())

    asyncio.run(collect_lab_observations(broker, instruments=["frxXAUUSD"], run_id="t1"))

    requested = {call.args[0] for call in broker.get_candles.await_args_list}
    assert "cryBTCUSD" in requested
    assert "cryETHUSD" in requested
    assert "frxXAUUSD" in requested


def test_crypto_specs_are_only_ever_fetched_at_their_own_declared_timeframe():
    broker = Mock()
    broker.get_candles = AsyncMock(return_value=_bars())

    asyncio.run(collect_lab_observations(broker, instruments=["frxXAUUSD"], run_id="t1"))

    crypto_calls = [call for call in broker.get_candles.await_args_list if call.args[0] in ("cryBTCUSD", "cryETHUSD")]
    assert crypto_calls  # sanity: it was actually called at all
    for call in crypto_calls:
        assert call.args[1] == lab_collector._GRANULARITY["H1"]


def test_ordinary_specs_never_get_widened_to_crypto_instruments():
    """An override-less spec (e.g. core_h1) must keep scanning exactly the
    global CFD_INSTRUMENTS list it was passed -- the per-spec override is
    opt-in, never a global widening."""
    broker = Mock()
    broker.get_candles = AsyncMock(return_value=_bars())

    observations = asyncio.run(collect_lab_observations(broker, instruments=["frxXAUUSD"], run_id="t1"))

    core_h1_rows = [o for o in observations if o.get("account") == "core_h1"]
    assert core_h1_rows
    assert all(o["instrument"] == "frxXAUUSD" for o in core_h1_rows)


def test_crypto_accounts_are_seeded_as_shadow_tier_with_no_strategy_tag():
    accounts = virtual_accounts.ensure_virtual_accounts()
    for account_id in ("crypto_btc_h1", "crypto_eth_h1"):
        assert accounts[account_id]["execution_tier"] == virtual_accounts.SHADOW
        assert accounts[account_id]["strategy_tag"] is None

from trading.cfd.breakout import DonchianBreakoutStrategy
from trading.cfd.lab_collector import _strategy_for_tag
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

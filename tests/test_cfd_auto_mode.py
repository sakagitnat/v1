from trading.cfd.auto_mode import choose_autonomous_mode
from trading.cfd.operating_mode import AGGRESSIVE, DEFENSIVE, NORMAL, RECOVERY

def test_auto_mode_reduces_risk_on_drawdown():
    assert choose_autonomous_mode("moderate", NORMAL)[0] == DEFENSIVE
    assert choose_autonomous_mode("deep", NORMAL)[0] == RECOVERY
    assert choose_autonomous_mode("severe", AGGRESSIVE)[0] == RECOVERY

def test_auto_mode_never_raises_risk():
    assert choose_autonomous_mode("normal", DEFENSIVE)[0] == DEFENSIVE
    assert choose_autonomous_mode("normal", RECOVERY)[0] == RECOVERY

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Action(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    symbol: str
    action: Action
    price: float
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    reason: str = ""

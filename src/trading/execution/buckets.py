import json
from pathlib import Path

_BUCKETS_PATH = Path(__file__).resolve().parents[3] / "state" / "buckets.json"

DEFAULT_BUCKETS = {
    "safe": {"cash": 0.0, "strategy": "mean_reversion"},
    "risk1": {"cash": 0.0, "strategy": "breakout"},
}

BLOWN_THRESHOLD = 5.0  # a risk bucket below this is "blown": paused until refilled


def load_buckets() -> dict:
    if not _BUCKETS_PATH.exists():
        return {}
    return json.loads(_BUCKETS_PATH.read_text())


def save_buckets(buckets: dict) -> None:
    _BUCKETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _BUCKETS_PATH.write_text(json.dumps(buckets, indent=2) + "\n")


def init_buckets_if_needed() -> dict:
    buckets = load_buckets()
    if not buckets:
        buckets = {k: dict(v) for k, v in DEFAULT_BUCKETS.items()}
        save_buckets(buckets)
    return buckets


def is_risk_bucket(name: str) -> bool:
    return name != "safe"


def is_blown(bucket: dict) -> bool:
    return is_risk_bucket_cash(bucket) < BLOWN_THRESHOLD


def is_risk_bucket_cash(bucket: dict) -> float:
    return bucket.get("cash", 0.0)


def rebalance(buckets: dict, growth_capital: float, safe_fraction: float = 0.5) -> dict:
    """Top up each bucket's cash toward its target share of growth_capital
    (equity above the protected capital floor). Never reduces a bucket's
    cash here -- that only happens through its own trading losses, tracked
    separately as positions open/close. New profit tops buckets up; it
    never claws back what a bucket already has.

    The safe bucket's target is `safe_fraction` of growth_capital. The rest
    is a shared pool for all risk buckets: a blown risk bucket (cash below
    BLOWN_THRESHOLD) is refilled first from that pool, before any leftover
    is spread across the other risk buckets -- "profit from risk buckets
    restarts a risk bucket that blew up."

    This is a simplified accounting model: it compares against each
    bucket's uninvested cash only, not the current value of whatever that
    bucket has invested in open positions, so it can be imprecise while
    positions are open. Alpaca's own buying power is the hard backstop --
    an order this drift makes too large simply gets rejected rather than
    overspending the real account -- so the imprecision is safe, not
    dangerous.
    """
    buckets = {k: dict(v) for k, v in buckets.items()}
    safe_target = growth_capital * safe_fraction

    if "safe" in buckets and buckets["safe"]["cash"] < safe_target:
        buckets["safe"]["cash"] = safe_target

    risk_names = [k for k in buckets if is_risk_bucket(k)]
    if risk_names:
        risk_pool_target = growth_capital * (1 - safe_fraction)
        already_have = sum(buckets[k]["cash"] for k in risk_names)
        available_to_add = max(0.0, risk_pool_target - already_have)
        if available_to_add > 0:
            blown = [k for k in risk_names if is_blown(buckets[k])]
            targets = blown or risk_names
            share = available_to_add / len(targets)
            for k in targets:
                buckets[k]["cash"] += share

    return buckets

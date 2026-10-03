"""Shared contract every strategy implements.

Port of lib/strategies/types.ts + lib/strategies/helpers.ts.

Every strategy is the same shape: (snapshot, history) -> Signal. The live
runner feeds it real Chainlink price + CLOB order-book data; nothing else in
the process needs to know which strategy it is talking to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

# Direction values. "BOTH" is for arbitrage-style strategies that buy both
# sides at once -- the UI renders it as its own colour rather than up/down.
YES = "YES"
NO = "NO"
BOTH = "BOTH"
NEUTRAL = "NEUTRAL"

DIRECTIONS = (YES, NO, BOTH, NEUTRAL)

WINDOW_SECONDS = 300


@dataclass
class MarketSnapshot:
    """A single point-in-time view of one 5-minute BTC Up/Down market."""

    condition_id: str
    price_to_beat: float  # Chainlink BTC/USD price at window open (the strike)
    current_price: float  # current Chainlink BTC/USD price
    yes_price: float  # Up token midpoint price (0-1)
    no_price: float  # Down token midpoint price (0-1)
    seconds_remaining: int  # seconds left in the 5-min window
    timestamp: int  # ms epoch
    asset: str = "BTC"
    yes_bid_ask_spread: float = 0.01

    # Real order-book quotes from the Polymarket CLOB. Buy at the ask, sell at
    # the bid. Optional because the book may not have arrived yet.
    up_bid: Optional[float] = None
    up_ask: Optional[float] = None
    down_bid: Optional[float] = None
    down_ask: Optional[float] = None

    # True while the strike price for this window hasn't been confirmed yet.
    price_to_beat_pending: bool = False
    question: Optional[str] = None  # "Bitcoin Up or Down - July 22, 2:30AM-2:35AM ET"
    eth_price: Optional[float] = None  # Chainlink ETH/USD -- used by cross-market lead-lag

    def to_dict(self) -> dict:
        """Wire format for the browser (camelCase, same shape as the original)."""
        return {
            "conditionId": self.condition_id,
            "asset": self.asset,
            "priceToBeat": self.price_to_beat,
            "currentPrice": self.current_price,
            "yesPrice": self.yes_price,
            "noPrice": self.no_price,
            "yesBidAskSpread": self.yes_bid_ask_spread,
            "secondsRemaining": self.seconds_remaining,
            "timestamp": self.timestamp,
            "upBid": self.up_bid,
            "upAsk": self.up_ask,
            "downBid": self.down_bid,
            "downAsk": self.down_ask,
            "priceToBeatPending": self.price_to_beat_pending,
            "question": self.question,
            "ethPrice": self.eth_price,
        }


@dataclass
class MarketHistory:
    """Rolling history a strategy can look back over (most recent last)."""

    snapshots: list[MarketSnapshot] = field(default_factory=list)


@dataclass
class Signal:
    direction: str  # one of DIRECTIONS
    confidence: float  # 0-1, how strongly the strategy believes this
    note: str  # short human-readable reason, shown in the UI

    def to_dict(self) -> dict:
        return {"direction": self.direction, "confidence": self.confidence, "note": self.note}


class Strategy:
    """Base class. Subclasses set id/name/description and implement evaluate()."""

    id: str = ""
    name: str = ""
    description: str = ""

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# helpers (port of lib/strategies/helpers.ts)
# ---------------------------------------------------------------------------


def clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def up_ask_of(s: MarketSnapshot) -> float:
    """Buy-side price for the Up token (falls back to the midpoint)."""
    return s.up_ask if s.up_ask is not None else s.yes_price


def down_ask_of(s: MarketSnapshot) -> float:
    """Buy-side price for the Down token (falls back to the midpoint)."""
    return s.down_ask if s.down_ask is not None else s.no_price


def elapsed_seconds(s: MarketSnapshot) -> int:
    """Seconds elapsed since this 5-minute window opened."""
    return WINDOW_SECONDS - s.seconds_remaining


def cents(price: float) -> str:
    return f"{price * 100:.1f}\u00a2"


def ema(values: list[float], period: int) -> list[float]:
    k = 2 / (period + 1)
    result = [values[0]]
    for i in range(1, len(values)):
        result.append(values[i] * k + result[i - 1] * (1 - k))
    return result


def resample_bars(
    history: MarketHistory, bar_seconds: int, pick: Callable[[MarketSnapshot], float]
) -> list[float]:
    """Resample the snapshot stream into fixed-width time bars (last value wins
    within each bar). Used to run indicators on e.g. 5-second bars regardless
    of how fast snapshots arrive."""
    snaps = history.snapshots
    if not snaps:
        return []
    bar_ms = bar_seconds * 1000
    bars: list[float] = []
    current_bucket = math.floor(snaps[0].timestamp / bar_ms)
    last_value = pick(snaps[0])
    for snap in snaps:
        bucket = math.floor(snap.timestamp / bar_ms)
        while bucket > current_bucket:
            bars.append(last_value)  # carry forward through empty buckets
            current_bucket += 1
        last_value = pick(snap)
    bars.append(last_value)
    return bars


def rsi(values: list[float], period: int) -> Optional[float]:
    """Classic RSI on a bar series; None if there aren't enough bars."""
    if len(values) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(len(values) - period, len(values)):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if gains + losses == 0:
        return 50.0
    return (100 * gains) / (gains + losses)


def pct_move_over(
    history: MarketHistory,
    seconds: float,
    pick: Callable[[MarketSnapshot], Optional[float]],
) -> Optional[float]:
    """Percentage move of a field over the trailing `seconds` (earliest
    in-range snapshot vs the latest). None when history doesn't reach back
    that far."""
    snaps = history.snapshots
    if len(snaps) < 2:
        return None
    last = snaps[-1]
    cutoff = last.timestamp - seconds * 1000

    ref_index = None
    for index, s in enumerate(snaps):
        if s.timestamp >= cutoff and pick(s) is not None:
            ref_index = index
            break

    from_value = pick(snaps[ref_index]) if ref_index is not None else None
    to_value = pick(last)
    if from_value is None or to_value is None or from_value == 0:
        return None
    if ref_index == len(snaps) - 1:
        return None
    return (to_value - from_value) / from_value


def sharpest_move_within(
    history: MarketHistory, seconds: float, slice_seconds: float = 10
) -> tuple[float, float]:
    """Largest BTC move over any trailing-10s slice within the last `seconds`.
    Returns (max_drop, max_pump): the most negative and most positive moves."""
    snaps = history.snapshots
    max_drop = 0.0
    max_pump = 0.0
    if len(snaps) < 2:
        return max_drop, max_pump
    cutoff = snaps[-1].timestamp - seconds * 1000
    j = 0
    for i in range(len(snaps)):
        if snaps[i].timestamp < cutoff:
            continue
        while snaps[i].timestamp - snaps[j].timestamp > slice_seconds * 1000:
            j += 1
        move = (snaps[i].current_price - snaps[j].current_price) / snaps[j].current_price
        if move < max_drop:
            max_drop = move
        if move > max_pump:
            max_pump = move
    return max_drop, max_pump


def sign(value: float) -> float:
    """JavaScript's Math.sign."""
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0

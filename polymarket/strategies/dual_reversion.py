"""Strategy 3 -- Low-Side Dual Reversion.

Port of lib/strategies/dualReversion.ts.

Up and Down must sum to $1.00 at settlement. When BOTH sides can be bought for
30-48c each (combined under 98c), buying the pair locks in the gap no matter
which side wins.
"""

from __future__ import annotations

from .base import (
    BOTH,
    NEUTRAL,
    MarketHistory,
    MarketSnapshot,
    Signal,
    Strategy,
    cents,
    clamp,
    down_ask_of,
    up_ask_of,
)

MAX_ASK_EITHER_SIDE = 0.48
MIN_ASK_EITHER_SIDE = 0.3
MAX_COMBINED_COST = 0.98
MIN_TIME_REMAINING = 120


class DualReversion(Strategy):
    id = "dual-reversion"
    name = "Low-Side Dual Reversion"
    description = (
        "When both sides are compressed into the 30-48\u00a2 band and together cost under 98\u00a2, it "
        "buys both. One side must pay $1 at settlement, so the discount is locked profit "
        "regardless of direction. Only enters with 2+ minutes left, while the book is still "
        "finding its midpoint."
    )

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        if snapshot.seconds_remaining < MIN_TIME_REMAINING:
            return Signal(NEUTRAL, 0, "Under 2 min left \u2014 asymmetric fill risk")

        up_ask = up_ask_of(snapshot)
        down_ask = down_ask_of(snapshot)
        combined = up_ask + down_ask
        hi = max(up_ask, down_ask)
        lo = min(up_ask, down_ask)

        if hi <= MAX_ASK_EITHER_SIDE and lo >= MIN_ASK_EITHER_SIDE and combined <= MAX_COMBINED_COST:
            return Signal(
                BOTH,
                clamp((1 - combined) * 6, 0.3, 1),
                f"{cents(up_ask)} + {cents(down_ask)} = {cents(combined)} for a guaranteed $1 "
                f"\u2014 {cents(1 - combined)} locked",
            )

        return Signal(NEUTRAL, 0, "Book not compressed (need both sides 30-48\u00a2)")


dual_reversion = DualReversion()

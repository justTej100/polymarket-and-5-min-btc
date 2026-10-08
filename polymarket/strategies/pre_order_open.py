"""Strategy 4 -- Pre-Order Market (Queue Positioning).

Port of lib/strategies/preOrderOpen.ts.

The spec places resting 45c bids on the NEXT window before it opens; in this
signal engine the equivalent is trading the first seconds of a fresh window,
while the book is still empty and both sides trade at a discount before the
midpoint is discovered.
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
    elapsed_seconds,
    up_ask_of,
)

OPENING_SECONDS = 45
SIDE_MIN = 0.3
SIDE_MAX = 0.6
MAX_COMBINED_COST = 0.97


class PreOrderOpen(Strategy):
    id = "pre-order-open"
    name = "Pre-Order (Opening Book)"
    description = (
        "Queue positioning: whoever has orders in when a new window opens gets the empty book's "
        "first (best) prices. Fires only in the first 45 seconds, when both sides sit in the "
        "30-60\u00a2 band and together cost under 97\u00a2 \u2014 buying the pair before equilibrium is "
        "found captures the opening discount."
    )

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        if elapsed_seconds(snapshot) > OPENING_SECONDS:
            return Signal(NEUTRAL, 0, "Opening window passed \u2014 waiting for next market")

        up_ask = up_ask_of(snapshot)
        down_ask = down_ask_of(snapshot)
        combined = up_ask + down_ask

        def in_band(p: float) -> bool:
            return SIDE_MIN <= p <= SIDE_MAX

        if in_band(up_ask) and in_band(down_ask) and combined <= MAX_COMBINED_COST:
            return Signal(
                BOTH,
                clamp((1 - combined) * 8, 0.3, 1),
                f"Fresh book: {cents(up_ask)} + {cents(down_ask)} = {cents(combined)} before "
                f"midpoint discovery",
            )

        return Signal(NEUTRAL, 0, "Opening book already efficient or one-sided")


pre_order_open = PreOrderOpen()

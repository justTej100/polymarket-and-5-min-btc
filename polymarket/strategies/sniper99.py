"""Strategy 2 -- 99c Sniper (Near-Resolution Strike).

Port of lib/strategies/sniper99.ts.

In the final minute, when spot is clearly past the strike, the winning side
often still asks 97-99c instead of $1.00. Buying that gap is a near-arb -- the
tail risk is a last-second candle flipping the outcome.
"""

from __future__ import annotations

from .base import (
    NEUTRAL,
    NO,
    YES,
    MarketHistory,
    MarketSnapshot,
    Signal,
    Strategy,
    cents,
    down_ask_of,
    up_ask_of,
)

MAX_TIME_REMAINING = 60
MIN_DISTANCE_PCT = 0.001  # spot must be >=0.1% past the strike (~$100 on BTC)
MAX_ASK = 0.99
MIN_ASK = 0.9  # if the book prices the "winner" below 90c, it disagrees with spot -- stay out


class Sniper99(Strategy):
    id = "sniper-99c"
    name = "99\u00a2 Sniper"
    description = (
        "Fires only in the final 60 seconds, and only when BTC is decisively past the strike "
        "(\u22650.1% away) while the winning side still asks \u226499\u00a2. Buys the near-certain "
        "winner for the last 1-3\u00a2 of edge and holds to settlement. Low variance \u2014 the rare "
        "killer is a last-second candle through the strike."
    )

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        seconds_remaining = snapshot.seconds_remaining
        current_price = snapshot.current_price
        price_to_beat = snapshot.price_to_beat

        if seconds_remaining > MAX_TIME_REMAINING:
            return Signal(NEUTRAL, 0, "Only fires in the final 60s")

        distance = current_price - price_to_beat
        if abs(distance) / price_to_beat < MIN_DISTANCE_PCT:
            return Signal(NEUTRAL, 0, "Spot too close to strike \u2014 flip risk too high")

        winning_side = YES if distance >= 0 else NO
        ask = up_ask_of(snapshot) if winning_side == YES else down_ask_of(snapshot)

        if ask > MAX_ASK:
            return Signal(NEUTRAL, 0, f"No discount left (winner asks {cents(ask)})")
        if ask < MIN_ASK:
            return Signal(NEUTRAL, 0, "Book disagrees with spot \u2014 skipping")

        label = "Up" if winning_side == YES else "Down"
        return Signal(
            winning_side,
            0.9,
            f"{label} at {cents(ask)} with ${abs(distance):.0f} of cushion, "
            f"{seconds_remaining}s left",
        )


sniper99 = Sniper99()

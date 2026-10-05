"""Strategy 1 -- 1c Buy (Ultra-Cheap Dislocation), in three flavors.

Port of lib/strategies/cheapDislocation.ts.

Same playbook, different definition of "cheap": wait ~45s for the market's
initial direction to form, buy the underdog side below the entry threshold,
then either take profit when it reprices or collect the full $1 on a true
reversal. Running the <5c / <30c / <40c versions side by side shows where the
underdog edge actually lives.
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
    elapsed_seconds,
    up_ask_of,
)

ENTRY_DELAY_SECONDS = 45


class LotteryVariant(Strategy):
    def __init__(self, id: str, name: str, description: str, entry_max: float, take_profit: float):
        self.id = id
        self.name = name
        self.description = description
        self.entry_max = entry_max
        self.take_profit = take_profit

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        entry_max = self.entry_max
        take_profit = self.take_profit

        if elapsed_seconds(snapshot) < ENTRY_DELAY_SECONDS:
            return Signal(NEUTRAL, 0, "Letting initial direction form (first 45s)")

        up_ask = up_ask_of(snapshot)
        down_ask = down_ask_of(snapshot)

        # Only one side can be the underdog -- buy the cheaper one if it's in range.
        if up_ask <= entry_max and up_ask < down_ask:
            return Signal(
                YES,
                0.3,
                f"Up at {cents(up_ask)} \u2014 underdog bid, {1 / up_ask:.1f}x if it reverses",
            )
        if down_ask <= entry_max and down_ask < up_ask:
            return Signal(
                NO,
                0.3,
                f"Down at {cents(down_ask)} \u2014 underdog bid, {1 / down_ask:.1f}x if it reverses",
            )

        # Hold zone: a ticket bought below the threshold that has repriced
        # toward the take-profit tier is still working -- keep it until then.
        cheap_side = YES if snapshot.yes_price <= snapshot.no_price else NO
        cheap_price = min(snapshot.yes_price, snapshot.no_price)
        if entry_max < cheap_price < take_profit:
            return Signal(
                cheap_side,
                0.3,
                f"Holding underdog at {cents(cheap_price)} \u2014 take profit at {cents(take_profit)}",
            )
        if cheap_price >= take_profit:
            return Signal(NEUTRAL, 0, f"Underdog hit {cents(take_profit)} \u2014 profit taken")

        return Signal(NEUTRAL, 0, f"No side cheap enough (need \u2264{cents(entry_max)})")


lottery_5c = LotteryVariant(
    id="lottery-5c",
    name="Lottery <5\u00a2",
    description=(
        "The pure lottery ticket: after the first 45s, buys any side under 5\u00a2 \u2014 priced as if "
        "reversals never happen. Takes profit if the fallen side reprices to 12\u00a2 (a 3-10x), or "
        "collects the full $1 on a true reversal. Small stakes: one winner pays for many duds."
    ),
    entry_max=0.05,
    take_profit=0.12,
)

lottery_30c = LotteryVariant(
    id="lottery-30c",
    name="Lottery <30\u00a2",
    description=(
        "Mid-priced underdog version: buys the losing side under 30\u00a2 after the first 45s. Less "
        "payoff per hit than the <5\u00a2 ticket (about 3x at full reversal) but fills far more often. "
        "Takes profit when the underdog reprices to 45\u00a2 \u2014 nearly back to a coin flip."
    ),
    entry_max=0.3,
    take_profit=0.45,
)

lottery_40c = LotteryVariant(
    id="lottery-40c",
    name="Lottery <40\u00a2",
    description=(
        "The tamest underdog version: buys any side under 40\u00a2 after the first 45s \u2014 barely a "
        "dislocation, more a slight-favorite fade. Takes profit at 50\u00a2 (back to even odds). Fills "
        "constantly; side by side with the <30\u00a2 and <5\u00a2 versions it shows where the underdog "
        "edge actually lives."
    ),
    entry_max=0.4,
    take_profit=0.5,
)

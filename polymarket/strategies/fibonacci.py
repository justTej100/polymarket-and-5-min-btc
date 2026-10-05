"""Strategy 7 -- Fibonacci Levels on the token price.

Port of lib/strategies/fibonacci.ts.

Anchor a fib grid to the swing high/low of the token's first 90 seconds, buy
dips into the 23.6-61.8% retracement zone, take profit at the 127.2% extension
(capped -- binary payoff tops out at $1).
"""

from __future__ import annotations

from typing import Optional

from .base import (
    NEUTRAL,
    NO,
    YES,
    MarketHistory,
    MarketSnapshot,
    Signal,
    Strategy,
    cents,
    elapsed_seconds,
)

OBSERVE_SECONDS = 90
MIN_TIME_REMAINING = 90
MIN_SWING_RANGE = 0.06  # need a >=6c swing for levels to mean anything
INVALIDATION_BUFFER = 0.02
EXTENSION = 0.272  # 127.2% extension beyond the swing high
EXTENSION_CAP = 0.9  # above 90c this becomes 99c-Sniper territory


def _evaluate_swing(
    series: list[float], current_price: float, direction: str, label: str
) -> Optional[Signal]:
    hi = max(series)
    lo = min(series)
    swing_range = hi - lo
    if swing_range < MIN_SWING_RANGE:
        return None

    if current_price < lo - INVALIDATION_BUFFER:
        return Signal(NEUTRAL, 0, f"Swing low broken on {label} \u2014 setup invalidated")

    zone_bottom = hi - 0.618 * swing_range  # deepest retracement we'll buy
    target = min(hi + EXTENSION * swing_range, EXTENSION_CAP)

    if current_price >= target:
        return Signal(
            NEUTRAL,
            0,
            f"{label} hit the 127.2% extension target ({cents(target)}) \u2014 profit taken",
        )
    if current_price >= zone_bottom:
        return Signal(
            direction,
            0.55,
            f"{label} in fib zone of the {cents(swing_range)} swing "
            f"({cents(zone_bottom)}\u2013{cents(hi)}), target {cents(target)}",
        )
    return Signal(NEUTRAL, 0, f"{label} below the 61.8% retracement \u2014 waiting")


class Fibonacci(Strategy):
    id = "fibonacci"
    name = "Fibonacci Levels"
    description = (
        "Observes the token price for the first 90 seconds, anchors Fibonacci retracements to "
        "that swing's high/low, then buys dips into the 23.6-61.8% zone of the dominant side. "
        "Takes profit at the 127.2% extension (capped at 90\u00a2), and invalidates the whole setup "
        "if the swing low breaks. Won't stage entries in the last 90 seconds."
    )

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        elapsed = elapsed_seconds(snapshot)
        if elapsed < OBSERVE_SECONDS:
            return Signal(NEUTRAL, 0, "Observing the first 90s swing")
        if snapshot.seconds_remaining < MIN_TIME_REMAINING:
            return Signal(NEUTRAL, 0, "Under 90s left \u2014 no time to manage entries")

        window_open_ms = snapshot.timestamp - elapsed * 1000
        observed = [
            s for s in history.snapshots if s.timestamp <= window_open_ms + OBSERVE_SECONDS * 1000
        ]
        if len(observed) < 10:
            return Signal(NEUTRAL, 0, "Not enough history from the observation window")

        # Run the grid on whichever side rallied during the observation window.
        yes_series = [s.yes_price for s in observed]
        up_swing = yes_series[-1] >= yes_series[0]
        if up_swing:
            signal = _evaluate_swing(yes_series, snapshot.yes_price, YES, "Up")
        else:
            signal = _evaluate_swing(
                [s.no_price for s in observed], snapshot.no_price, NO, "Down"
            )

        return signal or Signal(NEUTRAL, 0, "First-90s swing too small (<6\u00a2) for fib levels")


fibonacci = Fibonacci()

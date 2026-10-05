"""Strategy 9 -- Dump-Hedge (Sharp Move Arbitrage).

Port of lib/strategies/dumpHedge.ts.

A violent BTC move sends one side to near-zero while stale quotes linger on the
other. Buy the collapsed side immediately; if the elevated side can still be
had for a combined cost under 98c, hedge it for a locked edge. Otherwise run
the collapsed leg naked as a reversal play.
"""

from __future__ import annotations

from typing import Optional

from .base import (
    BOTH,
    NEUTRAL,
    NO,
    YES,
    MarketHistory,
    MarketSnapshot,
    Signal,
    Strategy,
    cents,
    down_ask_of,
    pct_move_over,
    sharpest_move_within,
    up_ask_of,
)

MOVE_PCT_THRESHOLD = 0.003  # 0.3% BTC move...
MOVE_WINDOW_SECONDS = 10  # ...within 10 seconds
MAX_ENTRY = 0.15  # collapsed side must still be cheap
HEDGE_MAX_COMBINED = 0.98
HOLD_WINDOW_SECONDS = 120  # manage the position while the event is recent
TAKE_PROFIT = 0.3  # naked leg exit once the reversal has repriced it
STOP_LOSS = 0.04  # cut if the collapsed side keeps bleeding


def _manage_side(
    collapsed_ask: float,
    other_ask: float,
    direction: str,
    fresh: bool,
    move_pct: float,
) -> Optional[Signal]:
    label = "Up" if direction == YES else "Down"
    combined = collapsed_ask + other_ask

    if fresh and collapsed_ask <= MAX_ENTRY:
        if combined <= HEDGE_MAX_COMBINED:
            return Signal(
                BOTH,
                0.8,
                f"Sharp move {move_pct * 100:.2f}% in 10s \u2014 hedged pair at {cents(combined)} "
                f"locks {cents(1 - combined)}",
            )
        return Signal(
            direction,
            0.45,
            f"Sharp move {move_pct * 100:.2f}% \u2014 {label} collapsed to {cents(collapsed_ask)}, "
            f"hedge too dear, naked reversal leg",
        )

    # Post-event management while the move is still recent.
    if collapsed_ask < STOP_LOSS:
        return Signal(
            NEUTRAL, 0, f"No reversal \u2014 {label} below {cents(STOP_LOSS)}, cutting"
        )
    if collapsed_ask >= TAKE_PROFIT:
        return Signal(
            NEUTRAL, 0, f"{label} recovered to {cents(collapsed_ask)} \u2014 profit taken"
        )
    if collapsed_ask < TAKE_PROFIT:
        if other_ask >= 0.75 and combined <= 1.0:
            return Signal(
                BOTH, 0.4, f"Holding hedged pair post-move ({cents(combined)} combined)"
            )
        return Signal(
            direction,
            0.35,
            f"Holding {label} reversal leg at {cents(collapsed_ask)}, target {cents(TAKE_PROFIT)}",
        )
    return None


class DumpHedge(Strategy):
    id = "dump-hedge"
    name = "Dump-Hedge"
    description = (
        "Purely reactive: when BTC moves \u22650.3% inside 10 seconds and one side collapses under "
        "15\u00a2, it buys the fallen side instantly. If the elevated side is still available for a "
        "combined cost under 98\u00a2 it hedges for a locked payout; otherwise it runs the leg "
        "naked, taking profit near 30\u00a2 or cutting below 4\u00a2. Never pre-positions."
    )

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        fresh_move = pct_move_over(history, MOVE_WINDOW_SECONDS, lambda s: s.current_price)
        fresh = fresh_move if fresh_move is not None else 0.0
        max_drop, max_pump = sharpest_move_within(
            history, HOLD_WINDOW_SECONDS, MOVE_WINDOW_SECONDS
        )
        up_ask = up_ask_of(snapshot)
        down_ask = down_ask_of(snapshot)

        # Dump: BTC fell, Up collapsed.
        if max_drop <= -MOVE_PCT_THRESHOLD and up_ask < TAKE_PROFIT + 0.01:
            signal = _manage_side(up_ask, down_ask, YES, fresh <= -MOVE_PCT_THRESHOLD, max_drop)
            if signal:
                return signal

        # Pump: BTC ripped, Down collapsed.
        if max_pump >= MOVE_PCT_THRESHOLD and down_ask < TAKE_PROFIT + 0.01:
            signal = _manage_side(down_ask, up_ask, NO, fresh >= MOVE_PCT_THRESHOLD, max_pump)
            if signal:
                return signal

        return Signal(NEUTRAL, 0, "No sharp move detected \u2014 waiting")


dump_hedge = DumpHedge()

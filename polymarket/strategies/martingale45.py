"""Strategy 6 -- Martingale / Anti-Martingale at 45c (auto mode).

Port of lib/strategies/martingale45.ts.

Mid-priced tokens (~45c) mean "50/50, we don't know" -- maximum reversion
potential. The regime gate decides which book to run:
    chop  -> martingale side: buy the dip side near 45c, sell the snap back to mid
    trend -> anti-martingale: buy the trending side near 45-60c and ride it
The spec's add-on ladders are approximated by re-entry after a flatten.
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
)

REGIME_LOOKBACK_SECONDS = 120
CHOP_MAX_RANGE_PCT = 0.0015  # <=0.15% BTC range in 2 min = chop
TREND_MIN_NET_PCT = 0.0012  # >=0.12% sustained net move = trend
ENTRY_LOW = 0.3
ENTRY_HIGH = 0.48
TREND_ENTRY_HIGH = 0.6


class Martingale45(Strategy):
    id = "martingale-45"
    name = "Martingale @ 45\u00a2"
    description = (
        "Regime-gated mid-price trading. In confirmed chop (BTC range under 0.15% for 2 min) it "
        "buys the dipped side in the 30-48\u00a2 zone and sells the reversion back above mid. In a "
        "confirmed trend it flips to anti-martingale: buy the trending side at 42-60\u00a2 and ride "
        "it. Sits out when the regime is unclear \u2014 martingale into a trend is how binary "
        "accounts die."
    )

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        last = snapshot.timestamp
        recent = [s for s in history.snapshots if s.timestamp >= last - REGIME_LOOKBACK_SECONDS * 1000]
        if len(recent) < 20 or last - recent[0].timestamp < 60_000:
            return Signal(NEUTRAL, 0, "Reading the regime (needs ~2 min of data)")

        prices = [s.current_price for s in recent]
        hi = max(prices)
        lo = min(prices)
        range_pct = (hi - lo) / snapshot.current_price
        net_pct = (prices[-1] - prices[0]) / prices[0]

        trending = abs(net_pct) >= TREND_MIN_NET_PCT and abs(net_pct) >= range_pct * 0.6
        chopping = not trending and range_pct <= CHOP_MAX_RANGE_PCT

        if trending:
            direction = YES if net_pct > 0 else NO
            price = snapshot.yes_price if direction == YES else snapshot.no_price
            if ENTRY_LOW <= price <= TREND_ENTRY_HIGH:
                trend_word = "up" if net_pct > 0 else "down"
                label = "Up" if direction == YES else "Down"
                return Signal(
                    direction,
                    0.5,
                    f"Anti-martingale: BTC trending {trend_word} {net_pct * 100:.2f}%, riding "
                    f"{label} at {cents(price)}",
                )
            return Signal(NEUTRAL, 0, "Trend confirmed but trend side outside entry zone")

        if chopping:
            direction = YES if snapshot.yes_price <= snapshot.no_price else NO
            price = min(snapshot.yes_price, snapshot.no_price)
            if ENTRY_LOW <= price <= ENTRY_HIGH:
                label = "Up" if direction == YES else "Down"
                return Signal(
                    direction,
                    0.5,
                    f"Chop regime (range {range_pct * 100:.2f}%): buying dipped {label} at "
                    f"{cents(price)}, target mid",
                )
            return Signal(NEUTRAL, 0, "Chop regime but no side dipped into 30-48\u00a2")

        return Signal(NEUTRAL, 0, "Regime unclear \u2014 neither chop nor trend")


martingale45 = Martingale45()

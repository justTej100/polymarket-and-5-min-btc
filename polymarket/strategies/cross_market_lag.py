"""Strategy 5 -- Cross-Market Bot (Lead-Lag).

Port of lib/strategies/crossMarketLag.ts.

BTC and ETH are tightly correlated on short timeframes but reprice with a 5-30
second lag. We stream Chainlink ETH/USD alongside BTC: when ETH makes a sharp
move and BTC hasn't followed yet -- and the BTC token in that direction hasn't
repriced -- we buy the lagging BTC market ahead of the catch-up move.
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
    clamp,
    pct_move_over,
    sign,
)

LOOKBACK_SECONDS = 30
MIN_LEAD_MOVE_PCT = 0.0025  # 0.25% ETH move in 30s
FOLLOW_RATIO = 0.4  # if BTC already moved 40% as much, the edge is gone
MAX_TOKEN_PRICE = 0.7  # skip if that side has already repriced


class CrossMarketLag(Strategy):
    id = "cross-market-lag"
    name = "Cross-Market Lag (ETH leads)"
    description = (
        "Watches Chainlink ETH/USD next to BTC. When ETH moves \u22650.25% in 30 seconds and BTC "
        "hasn't followed yet (nor has the token repriced past 70\u00a2), it buys the BTC market in "
        "ETH's direction \u2014 correlated assets reprice with a 5-30s lag, and this front-runs the "
        "catch-up."
    )

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        if snapshot.eth_price is None:
            return Signal(NEUTRAL, 0, "No ETH feed on this data source")

        eth_move = pct_move_over(history, LOOKBACK_SECONDS, lambda s: s.eth_price)
        btc_move = pct_move_over(history, LOOKBACK_SECONDS, lambda s: s.current_price)
        if eth_move is None or btc_move is None:
            return Signal(NEUTRAL, 0, "Building 30s of dual-feed history")

        if abs(eth_move) < MIN_LEAD_MOVE_PCT:
            return Signal(NEUTRAL, 0, "No sharp ETH move to lead")

        same_direction = sign(btc_move) == sign(eth_move)
        if same_direction and abs(btc_move) >= abs(eth_move) * FOLLOW_RATIO:
            return Signal(NEUTRAL, 0, "BTC already followed ETH \u2014 edge gone")

        direction = YES if eth_move > 0 else NO
        token_price = snapshot.yes_price if direction == YES else snapshot.no_price
        if token_price > MAX_TOKEN_PRICE:
            return Signal(NEUTRAL, 0, f"Token already repriced to {cents(token_price)}")

        arrow = "+" if eth_move > 0 else ""
        label = "Up" if direction == YES else "Down"
        return Signal(
            direction,
            clamp(abs(eth_move) / 0.005, 0.4, 0.9),
            f"ETH {arrow}{eth_move * 100:.2f}% in 30s, BTC lagging \u2014 buy {label} at "
            f"{cents(token_price)}",
        )


cross_market_lag = CrossMarketLag()

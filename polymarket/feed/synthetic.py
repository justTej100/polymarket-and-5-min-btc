"""Synthetic 5-minute window for local simulation when historical APIs fail.

Port of lib/polymarket/syntheticWindow.ts.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from polymarket.strategies.base import MarketSnapshot


@dataclass
class HistoricalWindow:
    condition_id: str
    price_to_beat: float
    final_outcome: str  # "YES" | "NO"
    snapshots: list[MarketSnapshot]


def generate_synthetic_window() -> HistoricalWindow:
    """Random-walk BTC + logistic YES prices over ~150 ticks (2s apart)."""
    ticks = 150
    price_to_beat = 65000 + round((random.random() - 0.5) * 200)
    price = float(price_to_beat)

    snapshots: list[MarketSnapshot] = []
    start = int(time.time() * 1000) - ticks * 2000

    for i in range(ticks):
        price += (random.random() - 0.5) * 15
        seconds_remaining = max(0, 300 - i * 2)
        diff = price - price_to_beat
        yes_price = min(0.99, max(0.01, 1 / (1 + math.exp(-diff / 20))))
        yes_price = round(yes_price * 1000) / 1000
        no_price = round((1 - yes_price) * 1000) / 1000
        current = round(price * 100) / 100
        half_spread = 0.005

        snapshots.append(
            MarketSnapshot(
                condition_id="synthetic-demo-window",
                asset="BTC",
                price_to_beat=float(price_to_beat),
                current_price=current,
                yes_price=yes_price,
                no_price=no_price,
                yes_bid_ask_spread=0.01,
                seconds_remaining=seconds_remaining,
                timestamp=start + i * 2000,
                up_bid=max(0.01, yes_price - half_spread),
                up_ask=min(0.99, yes_price + half_spread),
                down_bid=max(0.01, no_price - half_spread),
                down_ask=min(0.99, no_price + half_spread),
                question="Synthetic demo window",
            )
        )

    final_outcome = "YES" if price >= price_to_beat else "NO"
    return HistoricalWindow(
        condition_id="synthetic-demo-window",
        price_to_beat=float(price_to_beat),
        final_outcome=final_outcome,
        snapshots=snapshots,
    )

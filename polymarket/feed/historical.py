"""Real historical data for the simulation page.

Port of lib/polymarket/historicalClient.ts.

Stitched from:
  - Gamma:   which resolved 5-min BTC window to replay + its final outcome
  - CLOB:    prices-history for the Up token
  - Binance: 1-second BTC/USDT klines for the underlying price path

The BTC path comes from Binance rather than Chainlink (no public REST
history), so the strike is approximated by the window's opening kline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import urllib.error
import urllib.request
from typing import Optional

from polymarket.feed.gamma_client import (
    WINDOW_SECONDS,
    fetch_btc_market_for_window,
    window_start_sec,
)
from polymarket.feed.synthetic import HistoricalWindow
from polymarket.strategies.base import MarketSnapshot

CLOB_REST_BASE = "https://clob.polymarket.com"
BINANCE_REST_BASE = "https://api.binance.com"
REQUEST_TIMEOUT_SECONDS = 15

log = logging.getLogger("historical")


def _get_json(url: str):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"request failed: {response.status} for {url}")
        return json.loads(response.read().decode("utf-8"))


async def _fetch_token_price_history(
    token_id: str, start_sec: int, end_sec: int
) -> list[dict]:
    url = (
        f"{CLOB_REST_BASE}/prices-history?market={token_id}"
        f"&startTs={start_sec}&endTs={end_sec}&fidelity=1"
    )
    data = await asyncio.to_thread(_get_json, url)
    history = data.get("history") if isinstance(data, dict) else None
    return history if isinstance(history, list) else []


async def _fetch_btc_klines(start_sec: int, end_sec: int) -> list[dict]:
    url = (
        f"{BINANCE_REST_BASE}/api/v3/klines?symbol=BTCUSDT&interval=1s"
        f"&startTime={start_sec * 1000}&endTime={end_sec * 1000}"
        f"&limit={WINDOW_SECONDS}"
    )
    rows = await asyncio.to_thread(_get_json, url)
    if not isinstance(rows, list):
        raise RuntimeError("Binance klines returned unexpected payload")
    return [
        {"t": int(int(row[0]) / 1000), "p": float(row[4])}
        for row in rows
        if isinstance(row, (list, tuple)) and len(row) > 4
    ]


def _token_price_at(history: list[dict], sec: int, fallback: float) -> float:
    price = fallback
    for point in history:
        t = point.get("t")
        p = point.get("p")
        if t is None or p is None:
            continue
        if t > sec:
            break
        price = float(p)
    return price


def _shuffle(items: list[int]) -> list[int]:
    arr = list(items)
    random.shuffle(arr)
    return arr


async def _fetch_window(start_sec: int) -> HistoricalWindow:
    end_sec = start_sec + WINDOW_SECONDS
    market = await fetch_btc_market_for_window(start_sec)

    up_history, klines = await asyncio.gather(
        _fetch_token_price_history(market.up_token_id, start_sec - 60, end_sec),
        _fetch_btc_klines(start_sec, end_sec),
    )

    if len(klines) < 30:
        raise RuntimeError(f"not enough BTC klines for window {start_sec}")

    price_to_beat = klines[0]["p"]
    final_outcome: str = market.final_outcome or (
        "YES" if klines[-1]["p"] >= price_to_beat else "NO"
    )

    snapshots: list[MarketSnapshot] = []
    half_spread = 0.005
    for i in range(0, len(klines), 2):
        kline = klines[i]
        up_price = min(0.99, max(0.01, _token_price_at(up_history, kline["t"], 0.5)))
        no_price = round((1 - up_price) * 1000) / 1000
        snapshots.append(
            MarketSnapshot(
                condition_id=market.condition_id,
                asset="BTC",
                price_to_beat=price_to_beat,
                current_price=kline["p"],
                yes_price=up_price,
                no_price=no_price,
                yes_bid_ask_spread=0.01,
                seconds_remaining=max(0, end_sec - kline["t"]),
                timestamp=kline["t"] * 1000,
                up_bid=max(0.01, up_price - half_spread),
                up_ask=min(0.99, up_price + half_spread),
                down_bid=max(0.01, no_price - half_spread),
                down_ask=min(0.99, no_price + half_spread),
                question=market.question,
            )
        )

    return HistoricalWindow(
        condition_id=market.condition_id,
        price_to_beat=price_to_beat,
        final_outcome=final_outcome,
        snapshots=snapshots,
    )


async def fetch_historical_window() -> HistoricalWindow:
    """Picks a random recent resolved window; retries a few on missing data."""
    current = window_start_sec()
    candidates = _shuffle(
        [current - (i + 2) * WINDOW_SECONDS for i in range(11)]
    )

    last_error: Optional[BaseException] = None
    for start_sec in candidates[:4]:
        try:
            return await _fetch_window(start_sec)
        except Exception as err:  # noqa: BLE001
            last_error = err
            log.info("historical window %s failed: %s", start_sec, err)

    if last_error is not None:
        raise last_error
    raise RuntimeError("no historical window available")

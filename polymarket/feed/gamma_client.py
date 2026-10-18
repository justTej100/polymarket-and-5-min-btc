"""Polymarket Gamma API -- market discovery.

Port of lib/polymarket/gammaClient.ts.

Gamma is used for *discovery*: finding the currently-active 5-minute BTC
Up/Down market and its metadata (token ids, open/close times). The CLOB
WebSocket (clob_ws.py) handles live order-book *streaming* once we know the
token ids.

5-minute Up/Down market slugs are fully deterministic:
    btc-updown-5m-{unixWindowStart}   where windowStart % 300 == 0
so we never have to search -- we compute the slug from the clock.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import urllib.error
from dataclasses import dataclass
from typing import Optional

from polymarket.feed.http import get_json

GAMMA_BASE = "https://gamma-api.polymarket.com"

WINDOW_SECONDS = 5 * 60
WINDOW_MS = WINDOW_SECONDS * 1000

REQUEST_TIMEOUT_SECONDS = 10


@dataclass
class ActiveMarketMeta:
    condition_id: str
    slug: str
    question: str
    up_token_id: str
    down_token_id: str
    open_time_ms: int
    close_time_ms: int
    closed: bool = False
    # "YES" (Up) | "NO" (Down) | None if not resolved yet.
    final_outcome: Optional[str] = None


def window_start_sec(now_ms: Optional[int] = None) -> int:
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    return math.floor(now_ms / WINDOW_MS) * WINDOW_SECONDS


def slug_for_window(start_sec: int) -> str:
    return f"btc-updown-5m-{start_sec}"


def _parse_market(market: dict, start_sec: int) -> ActiveMarketMeta:
    outcomes = json.loads(market.get("outcomes") or '["Up", "Down"]')
    token_ids = json.loads(market.get("clobTokenIds") or "[]")
    if len(token_ids) < 2:
        raise ValueError(f"Market {market.get('slug')} is missing clobTokenIds")

    # Map outcome labels to token indices instead of assuming order.
    up_index = next(
        (i for i, o in enumerate(outcomes) if re.search(r"up|yes", str(o), re.IGNORECASE)),
        -1,
    )
    down_index = 1 if up_index == 0 else 0

    final_outcome: Optional[str] = None
    if market.get("closed") and market.get("outcomePrices"):
        prices = [float(p) for p in json.loads(market["outcomePrices"])]
        if prices[up_index] > 0.5:
            final_outcome = "YES"
        elif prices[down_index] > 0.5:
            final_outcome = "NO"

    return ActiveMarketMeta(
        condition_id=market["conditionId"],
        slug=market.get("slug", slug_for_window(start_sec)),
        question=market.get("question") or market.get("slug") or slug_for_window(start_sec),
        up_token_id=token_ids[0 if up_index == -1 else up_index],
        down_token_id=token_ids[1 if up_index == -1 else down_index],
        open_time_ms=start_sec * 1000,
        close_time_ms=(start_sec + WINDOW_SECONDS) * 1000,
        closed=bool(market.get("closed")),
        final_outcome=final_outcome,
    )


async def fetch_btc_market_for_window(start_sec: int) -> ActiveMarketMeta:
    """Fetches one specific 5-min BTC window by its deterministic start
    timestamp. Works for past (resolved) windows too via the /markets/slug
    endpoint, which still serves markets that have dropped out of the list
    query."""
    slug = slug_for_window(start_sec)
    url = f"{GAMMA_BASE}/markets/slug/{slug}"
    try:
        market = await asyncio.to_thread(get_json, url, REQUEST_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"Gamma API request for {slug} failed: {err.code}") from err

    if not isinstance(market, dict) or not market.get("conditionId"):
        raise RuntimeError(f"No BTC 5-min market found for {slug}")
    return _parse_market(market, start_sec)


async def fetch_active_btc_market() -> ActiveMarketMeta:
    """Finds the currently active 5-minute BTC Up/Down market."""
    return await fetch_btc_market_for_window(window_start_sec())

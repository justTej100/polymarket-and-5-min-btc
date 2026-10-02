"""Polymarket CLOB order book: REST seed + WebSocket stream.

Port of the CLOB half of lib/polymarket/wsClient.ts.

The CLOB websocket streams the live order book for the Up/Down tokens: `book`
snapshots plus `price_change` events carrying best_bid/best_ask. We seed from
the REST /book endpoint first so strategies see real quotes immediately rather
than waiting for the first websocket frame.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import websockets

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
CLOB_REST_BASE = "https://clob.polymarket.com"

BASE_RECONNECT_DELAY_MS = 1_000
MAX_RECONNECT_DELAY_MS = 30_000
REQUEST_TIMEOUT_SECONDS = 10

log = logging.getLogger("clob")


@dataclass
class TokenQuote:
    bid: Optional[float] = None
    ask: Optional[float] = None


def best_bid(bids: Optional[list]) -> Optional[float]:
    if not bids:
        return None
    best = 0.0
    for level in bids:
        try:
            best = max(best, float(level["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    return best or None


def best_ask(asks: Optional[list]) -> Optional[float]:
    if not asks:
        return None
    best = float("inf")
    for level in asks:
        try:
            best = min(best, float(level["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    return best if best != float("inf") else None


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


async def seed_order_books(token_ids: list[str]) -> dict[str, TokenQuote]:
    """One-shot REST fetch of both books, so the first snapshot has real quotes."""

    async def fetch(token_id: str) -> tuple[str, Optional[TokenQuote]]:
        try:
            book = await asyncio.to_thread(_get_json, f"{CLOB_REST_BASE}/book?token_id={token_id}")
            return token_id, TokenQuote(bid=best_bid(book.get("bids")), ask=best_ask(book.get("asks")))
        except Exception as err:  # noqa: BLE001
            log.warning("failed to seed book for token %s...: %s", token_id[:8], err)
            return token_id, None

    results = await asyncio.gather(*(fetch(t) for t in token_ids))
    return {token_id: quote for token_id, quote in results if quote is not None}


class ClobBookStream:
    """Streams the book for exactly two tokens. Restart it (cancel + re-run)
    when the window rolls over to a new pair of token ids."""

    def __init__(
        self,
        up_token_id: str,
        down_token_id: str,
        on_quote: Callable[[str, TokenQuote], Awaitable[None]],
    ):
        self.up_token_id = up_token_id
        self.down_token_id = down_token_id
        self._on_quote = on_quote
        self._quotes: dict[str, TokenQuote] = {}
        self._reconnect_attempts = 0

    def set_quote(self, token_id: str, quote: TokenQuote) -> None:
        self._quotes[token_id] = quote

    async def run(self) -> None:
        subscribe = json.dumps(
            {"type": "market", "assets_ids": [self.up_token_id, self.down_token_id]}
        )
        while True:
            try:
                async with websockets.connect(CLOB_WS_URL, ping_interval=20) as socket:
                    self._reconnect_attempts = 0
                    await socket.send(subscribe)
                    log.info("subscribed to book for %s...", self.up_token_id[:8])
                    async for raw in socket:
                        try:
                            parsed = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            # Non-JSON frames (e.g. "PONG") are expected -- ignore.
                            continue
                        events = parsed if isinstance(parsed, list) else [parsed]
                        for event in events:
                            await self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                log.warning("websocket error: %s", err)

            delay_ms = min(
                BASE_RECONNECT_DELAY_MS * 2**self._reconnect_attempts, MAX_RECONNECT_DELAY_MS
            )
            self._reconnect_attempts += 1
            log.info("reconnecting in %dms (attempt %d)", delay_ms, self._reconnect_attempts)
            await asyncio.sleep(delay_ms / 1000)

    def _is_ours(self, token_id: Optional[str]) -> bool:
        return token_id in (self.up_token_id, self.down_token_id)

    async def _handle_event(self, event: dict) -> None:
        if not isinstance(event, dict):
            return

        if event.get("event_type") == "book":
            token_id = event.get("asset_id")
            if not self._is_ours(token_id):
                return
            quote = TokenQuote(bid=best_bid(event.get("bids")), ask=best_ask(event.get("asks")))
            self._quotes[token_id] = quote
            await self._on_quote(token_id, quote)
            return

        if event.get("event_type") == "price_change" and isinstance(
            event.get("price_changes"), list
        ):
            for change in event["price_changes"]:
                token_id = change.get("asset_id")
                if not self._is_ours(token_id):
                    continue
                prev = self._quotes.get(token_id) or TokenQuote()
                bid = _parse_float(change.get("best_bid"))
                ask = _parse_float(change.get("best_ask"))
                nxt = TokenQuote(
                    bid=bid if bid is not None else prev.bid,
                    ask=ask if ask is not None else prev.ask,
                )
                if nxt.bid != prev.bid or nxt.ask != prev.ask:
                    self._quotes[token_id] = nxt
                    await self._on_quote(token_id, nxt)


def _parse_float(value) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None  # NaN check

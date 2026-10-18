"""Chainlink price stream over Polymarket's real-time data socket (RTDS).

Port of the RTDS half of lib/polymarket/wsClient.ts.

This socket streams the Chainlink price -- the exact feed these markets resolve
against (the `resolutionSource` on every 5-min market). Subscribing also
returns a per-second backfill array, which is how we recover the "price to
beat" (the Chainlink price at window open).

One instance per symbol: BTC/USD drives the market snapshots, ETH/USD feeds
the cross-market lead-lag strategy. They get separate sockets so one feed's
backfill array can never be mistaken for the other's ticks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import websockets

RTDS_WS_URL = "wss://ws-live-data.polymarket.com"

BASE_RECONNECT_DELAY_MS = 1_000
MAX_RECONNECT_DELAY_MS = 30_000

log = logging.getLogger("rtds")


@dataclass
class PriceTick:
    timestamp_ms: int
    value: float


class ChainlinkStream:
    def __init__(self, symbol: str, on_ticks: Callable[[list[PriceTick], bool], Awaitable[None]]):
        self.symbol = symbol  # e.g. "btc/usd"
        self._on_ticks = on_ticks
        self._reconnect_attempts = 0
        self._scope = f"rtds:{symbol.split('/')[0]}"

    def _subscribe_message(self) -> str:
        # Symbol-scoped filters only return a one-shot backfill and then go
        # silent -- no live `update` frames. Empty filters stream every
        # Chainlink pair; we keep self.symbol in _handle_message.
        return json.dumps(
            {
                "action": "subscribe",
                "subscriptions": [
                    {
                        "topic": "crypto_prices_chainlink",
                        "type": "*",
                        "filters": "",
                    }
                ],
            }
        )

    async def run(self) -> None:
        """Connects and keeps reconnecting with exponential backoff, forever."""
        while True:
            try:
                async with websockets.connect(RTDS_WS_URL, ping_interval=20) as socket:
                    self._reconnect_attempts = 0
                    await socket.send(self._subscribe_message())
                    log.info("[%s] subscribed to %s", self._scope, self.symbol)
                    async for raw in socket:
                        try:
                            await self._handle_message(json.loads(raw))
                        except (json.JSONDecodeError, TypeError, ValueError):
                            # Non-JSON frames (e.g. "PONG") are expected -- ignore.
                            continue
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 -- any socket failure is a reconnect
                log.warning("[%s] websocket error: %s", self._scope, err)

            delay_ms = min(
                BASE_RECONNECT_DELAY_MS * 2**self._reconnect_attempts, MAX_RECONNECT_DELAY_MS
            )
            self._reconnect_attempts += 1
            log.info(
                "[%s] reconnecting in %dms (attempt %d)",
                self._scope,
                delay_ms,
                self._reconnect_attempts,
            )
            await asyncio.sleep(delay_ms / 1000)

    async def _handle_message(self, msg: dict) -> None:
        if not isinstance(msg, dict):
            return
        # Docs say crypto_prices_chainlink; the live socket currently also
        # delivers Chainlink prints under crypto_prices with symbol btc/usd.
        topic = msg.get("topic")
        if topic and topic not in ("crypto_prices_chainlink", "crypto_prices"):
            return
        payload = msg.get("payload")
        if not isinstance(payload, dict):
            return

        # BTC and ETH share the feed -- only keep our symbol.
        symbol = payload.get("symbol")
        if symbol and str(symbol).lower() != self.symbol.lower():
            return

        # Subscribe responses carry a per-second backfill array; live updates
        # carry a single { timestamp, value } payload.
        data = payload.get("data")
        if isinstance(data, list):
            ticks = []
            for point in data:
                tick = _to_tick(point)
                if tick:
                    ticks.append(tick)
            if ticks:
                await self._on_ticks(ticks, True)
            return

        if payload.get("value") is not None:
            tick = _to_tick(payload)
            if tick:
                await self._on_ticks([tick], False)


def _to_tick(point: dict) -> Optional[PriceTick]:
    try:
        value = float(point["value"])
    except (KeyError, TypeError, ValueError):
        return None
    timestamp = point.get("timestamp")
    try:
        timestamp_ms = int(float(timestamp))
    except (TypeError, ValueError):
        timestamp_ms = int(time.time() * 1000)
    return PriceTick(timestamp_ms=timestamp_ms, value=value)

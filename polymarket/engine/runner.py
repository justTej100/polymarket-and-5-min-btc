"""The live pipeline: feeds in, snapshots out.

Port of the pipeline half of lib/polymarket/wsClient.ts plus the tick loop from
lib/worker/liveLoop.ts, which were separate processes in the original and are
one asyncio task tree here.

    Gamma discovery -> Chainlink RTDS stream -> CLOB book stream -> snapshot
        -> market state -> 9 strategies -> paper trading -> browsers + DB

Everything downstream reads the same MarketSnapshot, so a strategy behaves
identically whether it's driving the board, the paper ledger or a real order.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from ..db.client import db
from ..feed.chainlink_ws import ChainlinkStream, PriceTick
from ..feed.clob_ws import ClobBookStream, TokenQuote, seed_order_books
from ..feed.gamma_client import ActiveMarketMeta, fetch_btc_market_for_window, window_start_sec
from ..feed.state import market_state
from ..strategies import STRATEGIES
from ..strategies.base import MarketHistory, MarketSnapshot
from .copy_trading import copy_trader
from .paper_trading import paper_engine

PRICE_BUFFER_LIMIT = 900  # ~15 min of 1Hz Chainlink ticks
BROADCAST_INTERVAL_MS = 500  # at most ~2 evaluations/pushes per second
ROLLOVER_POLL_SECONDS = 1

log = logging.getLogger("runner")


@dataclass
class _PipelineState:
    current_market: Optional[ActiveMarketMeta] = None
    price_to_beat: Optional[float] = None
    price_to_beat_pending: bool = False
    chainlink_ticks: list[PriceTick] = field(default_factory=list)
    latest_chainlink: Optional[PriceTick] = None
    latest_eth: Optional[PriceTick] = None
    quotes: dict[str, TokenQuote] = field(default_factory=dict)  # tokenId -> best bid/ask


S = _PipelineState()


def get_current_market() -> Optional[ActiveMarketMeta]:
    """The market currently being streamed (token ids etc.), if any."""
    return S.current_market


# ---------------------------------------------------------------------------
# Chainlink price buffer + price-to-beat
# ---------------------------------------------------------------------------


def _record_chainlink_tick(tick: PriceTick) -> None:
    if tick.value != tick.value or tick.value <= 0:  # NaN or non-positive
        return
    last = S.chainlink_ticks[-1] if S.chainlink_ticks else None
    if last and tick.timestamp_ms <= last.timestamp_ms:
        return  # keep sorted, dedupe
    S.chainlink_ticks.append(tick)
    if len(S.chainlink_ticks) > PRICE_BUFFER_LIMIT:
        del S.chainlink_ticks[: len(S.chainlink_ticks) - PRICE_BUFFER_LIMIT]
    if S.latest_chainlink is None or tick.timestamp_ms >= S.latest_chainlink.timestamp_ms:
        S.latest_chainlink = tick


def _resolve_price_to_beat() -> None:
    """The strike is the first Chainlink print at/after window open (mirrors
    how Polymarket resolves these markets). If our buffer doesn't reach back to
    the boundary (e.g. the server booted mid-window), we use the earliest tick
    we have and flag the snapshot so the UI can show it as provisional."""
    if S.current_market is None:
        return
    if S.price_to_beat is not None and not S.price_to_beat_pending:
        return

    open_ms = S.current_market.open_time_ms
    first_at_or_after_open = next(
        (t for t in S.chainlink_ticks if t.timestamp_ms >= open_ms), None
    )

    if first_at_or_after_open and first_at_or_after_open.timestamp_ms <= open_ms + 5_000:
        S.price_to_beat = first_at_or_after_open.value
        S.price_to_beat_pending = False
        return

    if S.price_to_beat is None and first_at_or_after_open:
        # We have post-open ticks but missed the boundary itself -- best effort.
        S.price_to_beat = first_at_or_after_open.value
        S.price_to_beat_pending = first_at_or_after_open.timestamp_ms > open_ms + 5_000
    elif S.price_to_beat is None and S.latest_chainlink:
        S.price_to_beat = S.latest_chainlink.value
        S.price_to_beat_pending = True


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------


def _midpoint(quote: Optional[TokenQuote]) -> Optional[float]:
    if quote is None:
        return None
    if quote.bid is not None and quote.ask is not None:
        return (quote.bid + quote.ask) / 2
    return quote.bid if quote.bid is not None else quote.ask


def _build_snapshot(timestamp_ms: int) -> Optional[MarketSnapshot]:
    if S.current_market is None or S.latest_chainlink is None or S.price_to_beat is None:
        return None

    up_quote = S.quotes.get(S.current_market.up_token_id)
    down_quote = S.quotes.get(S.current_market.down_token_id)
    up_mid = _midpoint(up_quote)
    down_mid = _midpoint(down_quote)

    # Until the book arrives, fall back to complementary pricing so the
    # strategies always see a sane 0-1 pair.
    if up_mid is not None:
        yes_price = up_mid
    elif down_mid is not None:
        yes_price = 1 - down_mid
    else:
        yes_price = 0.5
    no_price = down_mid if down_mid is not None else 1 - yes_price

    if up_quote and up_quote.bid is not None and up_quote.ask is not None:
        spread = max(0.0, up_quote.ask - up_quote.bid)
    else:
        spread = 0.01

    return MarketSnapshot(
        condition_id=S.current_market.condition_id,
        asset="BTC",
        price_to_beat=S.price_to_beat,
        current_price=S.latest_chainlink.value,
        yes_price=yes_price,
        no_price=no_price,
        yes_bid_ask_spread=spread,
        seconds_remaining=max(
            0, round((S.current_market.close_time_ms - timestamp_ms) / 1000)
        ),
        timestamp=timestamp_ms,
        up_bid=up_quote.bid if up_quote else None,
        up_ask=up_quote.ask if up_quote else None,
        down_bid=down_quote.bid if down_quote else None,
        down_ask=down_quote.ask if down_quote else None,
        price_to_beat_pending=S.price_to_beat_pending,
        question=S.current_market.question,
        eth_price=S.latest_eth.value if S.latest_eth else None,
    )


def _emit_snapshot(timestamp_ms: Optional[int] = None) -> None:
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    snapshot = _build_snapshot(timestamp_ms)
    if snapshot is None:
        return
    market_state.update(snapshot)
    paper_engine.on_snapshot(snapshot, market_state.get_history())


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

# Called with the JSON-ready payload dict on every broadcast tick.
BroadcastHandler = Callable[[dict], Awaitable[None]]


class LiveRunner:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._clob_task: Optional[asyncio.Task] = None
        self._clob_stream: Optional[ClobBookStream] = None
        self._dirty = asyncio.Event()
        self._broadcast_handlers: list[BroadcastHandler] = []
        self._latest_signals: list[dict] = []

    def on_broadcast(self, handler: BroadcastHandler) -> None:
        self._broadcast_handlers.append(handler)

    # -- feeds ---------------------------------------------------------------

    async def _on_btc_ticks(self, ticks: list[PriceTick], is_backfill: bool) -> None:
        for tick in ticks:
            _record_chainlink_tick(tick)
        _resolve_price_to_beat()
        latest = S.latest_chainlink
        _emit_snapshot(latest.timestamp_ms if latest else None)
        self._dirty.set()

    async def _on_eth_ticks(self, ticks: list[PriceTick], is_backfill: bool) -> None:
        # Only the latest value is kept -- the cross-market strategy reads its
        # history back out of the snapshot buffer.
        if ticks:
            S.latest_eth = ticks[-1]

    async def _on_quote(self, token_id: str, quote: TokenQuote) -> None:
        S.quotes[token_id] = quote
        _emit_snapshot()
        self._dirty.set()

    # -- window rollover -----------------------------------------------------

    async def _activate_window(self, start_sec: int, attempt: int = 0) -> None:
        while True:
            try:
                market = await fetch_btc_market_for_window(start_sec)
            except Exception as err:  # noqa: BLE001
                delay = min(1.0 * 2**attempt, 15.0)
                log.warning(
                    "failed to fetch window %d, retrying in %.0fms: %s",
                    start_sec,
                    delay * 1000,
                    err,
                )
                await asyncio.sleep(delay)
                # The window may not be listed yet right at the boundary --
                # retry, but recompute in case we crossed into the next one.
                start_sec = window_start_sec()
                attempt += 1
                continue

            S.current_market = market
            S.price_to_beat = None
            S.price_to_beat_pending = False
            S.quotes.clear()
            market_state.reset()
            db.reset_directions()
            _resolve_price_to_beat()
            log.info("active window %s (%s)", market.slug, market.question)

            S.quotes.update(await seed_order_books([market.up_token_id, market.down_token_id]))
            await self._resubscribe_clob(market)
            _emit_snapshot()
            self._dirty.set()
            return

    async def _resubscribe_clob(self, market: ActiveMarketMeta) -> None:
        if self._clob_task is not None:
            self._clob_task.cancel()
            try:
                await self._clob_task
            except asyncio.CancelledError:
                pass
            self._clob_task = None

        self._clob_stream = ClobBookStream(
            market.up_token_id, market.down_token_id, self._on_quote
        )
        for token_id, quote in S.quotes.items():
            self._clob_stream.set_quote(token_id, quote)
        self._clob_task = asyncio.create_task(self._clob_stream.run())

    async def _watch_for_rollover(self) -> None:
        while True:
            await asyncio.sleep(ROLLOVER_POLL_SECONDS)
            market = S.current_market
            if market is None:
                continue
            if time.time() * 1000 < market.close_time_ms:
                continue

            next_start = window_start_sec()
            log.info("window closed, rolling over to next 5-min market")

            # Settle every paper position at the final print before the reset.
            final_snapshot = market_state.get_latest()
            if final_snapshot is not None:
                paper_engine.on_window_end(final_snapshot)
                outcome = (
                    "UP"
                    if final_snapshot.current_price >= final_snapshot.price_to_beat
                    else "DOWN"
                )
                await db.resolve_market(final_snapshot.condition_id, outcome)

            await self._activate_window(next_start)

    # -- evaluation + broadcast ----------------------------------------------

    def _evaluate(self, snapshot: MarketSnapshot, history: list[MarketSnapshot]) -> list[dict]:
        market_history = MarketHistory(snapshots=history)
        signals = []
        for strategy in STRATEGIES:
            signal = strategy.evaluate(snapshot, market_history)
            signals.append(
                {
                    "id": strategy.id,
                    "name": strategy.name,
                    "description": strategy.description,
                    "signal": signal.to_dict(),
                    "_signal": signal,
                }
            )
        return signals

    def build_payload(self, include_history: bool = False) -> Optional[dict]:
        """The message every browser gets. The first message of a connection
        carries the full window history so the chart can draw immediately;
        after that they are snapshot deltas."""
        snapshot = market_state.get_latest()
        if snapshot is None:
            return None
        history = market_state.get_history()

        signals = self._latest_signals or self._evaluate(snapshot, history)

        payload = {
            "type": "tick",
            "snapshot": snapshot.to_dict(),
            "signals": [{k: v for k, v in s.items() if k != "_signal"} for s in signals],
            "paper": paper_engine.get_public_state(snapshot),
            "copy": copy_trader.get_status(),
        }
        if include_history:
            payload["history"] = [s.to_dict() for s in history]
        return payload

    async def _broadcast_loop(self) -> None:
        """Evaluates once per interval and shares the result with every
        subscriber and the database -- the original evaluated the strategies
        twice (once for the DB worker, once per SSE push)."""
        while True:
            await self._dirty.wait()
            self._dirty.clear()

            snapshot = market_state.get_latest()
            if snapshot is None:
                await asyncio.sleep(BROADCAST_INTERVAL_MS / 1000)
                continue

            history = market_state.get_history()
            self._latest_signals = self._evaluate(snapshot, history)

            # Persist only direction *changes* (the rule from liveLoop.ts).
            for entry in self._latest_signals:
                try:
                    wrote = await db.record_signal_if_changed(
                        snapshot, entry["id"], entry["_signal"]
                    )
                except Exception as err:  # noqa: BLE001
                    log.warning("signal persistence failed: %s", err)
                    wrote = False
                if wrote:
                    log.info(
                        "[signal] %s -> %s (%s)",
                        entry["id"],
                        entry["_signal"].direction,
                        entry["_signal"].note,
                    )

            payload = self.build_payload(include_history=False)
            if payload is not None:
                for handler in list(self._broadcast_handlers):
                    try:
                        await handler(payload)
                    except Exception as err:  # noqa: BLE001
                        log.warning("broadcast handler failed: %s", err)

            await asyncio.sleep(BROADCAST_INTERVAL_MS / 1000)

    # -- entry point ---------------------------------------------------------

    async def _window_loop(self) -> None:
        """Activates the current window, then watches for rollovers. Runs as a
        background task so a Gamma outage retries quietly instead of blocking
        the server from serving the page."""
        await self._activate_window(window_start_sec())
        await self._watch_for_rollover()

    async def start(self) -> None:
        """Starts the whole live pipeline as background tasks and returns
        immediately -- the page is served while the feeds are still coming up."""
        loop = asyncio.get_running_loop()
        copy_trader.attach(loop)
        await db.connect()

        btc = ChainlinkStream("btc/usd", self._on_btc_ticks)
        eth = ChainlinkStream("eth/usd", self._on_eth_ticks)
        self._tasks.append(asyncio.create_task(btc.run()))
        self._tasks.append(asyncio.create_task(eth.run()))
        self._tasks.append(asyncio.create_task(self._broadcast_loop()))
        self._tasks.append(asyncio.create_task(self._window_loop()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._clob_task is not None:
            self._clob_task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await db.close()


runner = LiveRunner()

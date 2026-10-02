"""In-memory market state.

Port of lib/worker/marketState.ts.

Lives entirely in this process's memory. Every WebSocket tick updates it, and
the browser push loop reads from it -- no polling, no DB round-trip on the hot
path. Only strategy *signals* get written to the DB (see db/client.py), not
every raw tick.

Guarded by a lock because the feed sockets run on the asyncio loop while the
copy trader's blocking SDK calls run on worker threads.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from ..strategies.base import MarketSnapshot

HISTORY_LIMIT = 360  # > one full 5-min window at ~1 snapshot/sec
HISTORY_MIN_GAP_MS = 900  # history is ~1Hz even if ticks come faster


class MarketState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._history: list[MarketSnapshot] = []
        self._latest: Optional[MarketSnapshot] = None
        self._listeners: list[Callable[[MarketSnapshot], None]] = []

    def on_update(self, listener: Callable[[MarketSnapshot], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def update(self, snapshot: MarketSnapshot) -> None:
        with self._lock:
            self._latest = snapshot

            # Keep `latest` real-time but sample history at ~1Hz so a burst of
            # order-book ticks can't evict the start of the window from the chart.
            last_kept = self._history[-1] if self._history else None
            if last_kept is None or snapshot.timestamp - last_kept.timestamp >= HISTORY_MIN_GAP_MS:
                self._history.append(snapshot)
                if len(self._history) > HISTORY_LIMIT:
                    self._history.pop(0)
            else:
                # Refresh the newest sample in place so quotes stay current.
                self._history[-1] = snapshot

            listeners = list(self._listeners)

        for listener in listeners:
            listener(snapshot)

    def get_latest(self) -> Optional[MarketSnapshot]:
        with self._lock:
            return self._latest

    def get_history(self) -> list[MarketSnapshot]:
        with self._lock:
            return list(self._history)

    def reset(self) -> None:
        with self._lock:
            self._history = []
            self._latest = None


# One shared instance for the whole process.
market_state = MarketState()

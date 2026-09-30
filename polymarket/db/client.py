"""Optional persistence: Neon/Postgres or local SQLite. No ORM.

Replaces lib/db.ts + the Prisma client, and carries over the persistence rule
from lib/worker/liveLoop.ts: a Signal row is only written when a strategy's
direction *changes*, never on every tick.

Backend selection:
  1. NEON_DATABASE_URL set  -> Postgres via psycopg
  2. DATABASE_URL=file:... or SQLITE_PATH set -> stdlib sqlite3
  3. else -> in-memory no-op (feed/strategies/paper/copy still work)

Every write is fire-and-forget: if the DB is down, the trading loop keeps
running and the error is logged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from ..strategies.base import BOTH, NEUTRAL, YES, MarketSnapshot, Signal

SCHEMA_PG = Path(__file__).with_name("schema.sql")
SCHEMA_SQLITE = Path(__file__).with_name("schema_sqlite.sql")

log = logging.getLogger("db")


def _resolve_sqlite_path() -> Optional[Path]:
    """Returns a filesystem path for SQLite, or None if not configured."""
    explicit = (os.environ.get("SQLITE_PATH") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        return None
    if database_url.startswith("file:"):
        # Prisma-style file:./dev.db or file:dev.db
        raw = database_url[5:]
        if raw.startswith("//"):
            # file:///absolute or file://localhost/path
            parsed = urlparse(database_url)
            path = parsed.path
            if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
                path = path[1:]
            return Path(path).expanduser().resolve()
        return Path(raw).expanduser().resolve()
    return None


class Database:
    """A single lazily-opened connection, guarded by a lock."""

    def __init__(
        self,
        neon_url: Optional[str] = None,
        sqlite_path: Optional[Path] = None,
    ) -> None:
        self._neon_url = (
            neon_url
            if neon_url is not None
            else (os.environ.get("NEON_DATABASE_URL") or "").strip()
        )
        self._sqlite_path = sqlite_path if sqlite_path is not None else _resolve_sqlite_path()
        self._backend: Optional[str] = None  # "postgres" | "sqlite"
        self._conn = None
        self._lock = asyncio.Lock()
        self._ready = False
        self._last_direction: dict[str, str] = {}
        self._market_ids: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._neon_url) or self._sqlite_path is not None

    # -- connection ----------------------------------------------------------

    async def connect(self) -> None:
        if not self.enabled:
            log.info("no database configured -- running in memory only")
            return
        async with self._lock:
            await self._ensure_connection()

    async def _ensure_connection(self) -> None:
        if self._backend == "postgres":
            if self._conn is not None and not self._conn.closed:
                return
            import psycopg

            self._conn = await psycopg.AsyncConnection.connect(self._neon_url, autocommit=True)
            if not self._ready:
                await self._conn.execute(SCHEMA_PG.read_text())
                self._ready = True
                log.info("connected to Postgres, schema applied")
            return

        if self._backend == "sqlite":
            if self._conn is not None:
                return
            assert self._sqlite_path is not None
            self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await asyncio.to_thread(sqlite3.connect, str(self._sqlite_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            if not self._ready:
                await asyncio.to_thread(self._conn.executescript, SCHEMA_SQLITE.read_text())
                await asyncio.to_thread(self._conn.commit)
                self._ready = True
                log.info("connected to SQLite at %s, schema applied", self._sqlite_path)
            return

        # First open: pick backend.
        if self._neon_url:
            self._backend = "postgres"
            await self._ensure_connection()
            return

        if self._sqlite_path is not None:
            self._backend = "sqlite"
            await self._ensure_connection()
            return

    async def close(self) -> None:
        async with self._lock:
            if self._backend == "postgres" and self._conn is not None and not self._conn.closed:
                await self._conn.close()
            elif self._backend == "sqlite" and self._conn is not None:
                await asyncio.to_thread(self._conn.close)
            self._conn = None

    # -- writes --------------------------------------------------------------

    async def ensure_market(self, condition_id: str, price_to_beat: float) -> Optional[str]:
        if not self.enabled:
            return None
        cached = self._market_ids.get(condition_id)
        if cached:
            return cached

        open_time = datetime.now(timezone.utc)
        close_time = open_time + timedelta(minutes=5)

        async with self._lock:
            try:
                await self._ensure_connection()
                if self._backend == "postgres":
                    async with self._conn.cursor() as cursor:
                        await cursor.execute(
                            """
                            INSERT INTO "Market" ("conditionId", "asset", "priceToBeat",
                                                  "openTime", "closeTime")
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT ("conditionId") DO UPDATE
                                SET "conditionId" = EXCLUDED."conditionId"
                            RETURNING "id"
                            """,
                            (condition_id, "BTC", price_to_beat, open_time, close_time),
                        )
                        row = await cursor.fetchone()
                    market_id = row[0] if row else None
                else:
                    market_id = str(uuid.uuid4())

                    def _upsert() -> Optional[str]:
                        existing = self._conn.execute(
                            "SELECT id FROM Market WHERE conditionId = ?",
                            (condition_id,),
                        ).fetchone()
                        if existing:
                            return existing["id"]
                        self._conn.execute(
                            """
                            INSERT INTO Market (id, conditionId, asset, priceToBeat, openTime, closeTime)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                market_id,
                                condition_id,
                                "BTC",
                                price_to_beat,
                                open_time.isoformat(),
                                close_time.isoformat(),
                            ),
                        )
                        self._conn.commit()
                        return market_id

                    market_id = await asyncio.to_thread(_upsert)
            except Exception as err:  # noqa: BLE001
                log.warning("could not upsert market %s: %s", condition_id, err)
                return None

        if market_id:
            self._market_ids[condition_id] = market_id
            if len(self._market_ids) > 50:
                self._market_ids.pop(next(iter(self._market_ids)))
        return market_id

    async def record_signal_if_changed(
        self, snapshot: MarketSnapshot, strategy_id: str, signal: Signal
    ) -> bool:
        previous = self._last_direction.get(strategy_id)

        if signal.direction == NEUTRAL:
            self._last_direction[strategy_id] = NEUTRAL
            return False
        if signal.direction == previous:
            return False

        self._last_direction[strategy_id] = signal.direction

        if not self.enabled:
            return False

        market_id = await self.ensure_market(snapshot.condition_id, snapshot.price_to_beat)
        if market_id is None:
            return False

        if signal.direction == BOTH:
            entry_cost_usd = snapshot.yes_price + snapshot.no_price
        elif signal.direction == YES:
            entry_cost_usd = snapshot.yes_price
        else:
            entry_cost_usd = snapshot.no_price

        async with self._lock:
            try:
                await self._ensure_connection()
                if self._backend == "postgres":
                    await self._conn.execute(
                        """
                        INSERT INTO "Signal" ("marketId", "strategyId", "direction",
                                              "confidence", "entryPrice", "entryCostUsd")
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            market_id,
                            strategy_id,
                            signal.direction,
                            signal.confidence,
                            entry_cost_usd,
                            entry_cost_usd,
                        ),
                    )
                else:

                    def _insert() -> None:
                        self._conn.execute(
                            """
                            INSERT INTO Signal (id, marketId, strategyId, direction,
                                                confidence, entryPrice, entryCostUsd)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                str(uuid.uuid4()),
                                market_id,
                                strategy_id,
                                signal.direction,
                                signal.confidence,
                                entry_cost_usd,
                                entry_cost_usd,
                            ),
                        )
                        self._conn.commit()

                    await asyncio.to_thread(_insert)
            except Exception as err:  # noqa: BLE001
                log.warning("could not write signal for %s: %s", strategy_id, err)
                return False
        return True

    async def resolve_market(self, condition_id: str, outcome: str) -> None:
        if not self.enabled:
            return
        async with self._lock:
            try:
                await self._ensure_connection()
                if self._backend == "postgres":
                    await self._conn.execute(
                        'UPDATE "Market" SET "resolved" = true, "outcome" = %s WHERE "conditionId" = %s',
                        (outcome, condition_id),
                    )
                else:

                    def _resolve() -> None:
                        self._conn.execute(
                            "UPDATE Market SET resolved = 1, outcome = ? WHERE conditionId = ?",
                            (outcome, condition_id),
                        )
                        self._conn.commit()

                    await asyncio.to_thread(_resolve)
            except Exception as err:  # noqa: BLE001
                log.warning("could not resolve market %s: %s", condition_id, err)

    def reset_directions(self) -> None:
        self._last_direction.clear()


db = Database()

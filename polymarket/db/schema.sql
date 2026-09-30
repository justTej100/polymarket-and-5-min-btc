-- Neon / Postgres schema.
--
-- Hand-written port of prisma/neon/schema.prisma from the original project.
-- Table and column names keep Prisma's exact casing (quoted, camelCase) so
-- this schema is drop-in compatible with a database the Next.js version
-- already created -- point NEON_DATABASE_URL at the old database and the rows
-- line up.
--
-- Prisma generated ids with cuid(); here Postgres generates them itself.
-- gen_random_uuid() is built in from Postgres 13 onward (and on Neon).
--
-- This file is applied automatically at startup (db/client.py), and every
-- statement is idempotent, so running it against an existing database is safe.

CREATE TABLE IF NOT EXISTS "Market" (
    "id"          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "conditionId" TEXT NOT NULL UNIQUE,
    "asset"       TEXT NOT NULL,
    "priceToBeat" DOUBLE PRECISION NOT NULL,
    "openTime"    TIMESTAMP(3) NOT NULL,
    "closeTime"   TIMESTAMP(3) NOT NULL,
    "resolved"    BOOLEAN NOT NULL DEFAULT false,
    "outcome"     TEXT
);

CREATE INDEX IF NOT EXISTS "Market_openTime_idx" ON "Market" ("openTime");

CREATE TABLE IF NOT EXISTS "Signal" (
    "id"             TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "marketId"       TEXT NOT NULL REFERENCES "Market" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    "strategyId"     TEXT NOT NULL,
    "direction"      TEXT NOT NULL,
    "confidence"     DOUBLE PRECISION,
    "entryPrice"     DOUBLE PRECISION,
    "entryCostUsd"   DOUBLE PRECISION,
    "createdAt"      TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "won"            BOOLEAN,
    "closedAt"       TIMESTAMP(3),
    "exitPrice"      DOUBLE PRECISION,
    "realizedPnlUsd" DOUBLE PRECISION,
    "exitReason"     TEXT,
    "result"         TEXT
);

CREATE INDEX IF NOT EXISTS "Signal_strategyId_idx" ON "Signal" ("strategyId");
CREATE INDEX IF NOT EXISTS "Signal_marketId_idx" ON "Signal" ("marketId");

CREATE TABLE IF NOT EXISTS "SignalEvent" (
    "id"             TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "signalId"       TEXT NOT NULL REFERENCES "Signal" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    "eventType"      TEXT NOT NULL,
    "price"          DOUBLE PRECISION,
    "quantity"       DOUBLE PRECISION,
    "realizedPnlUsd" DOUBLE PRECISION DEFAULT 0,
    "note"           TEXT,
    "createdAt"      TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS "SignalEvent_signalId_idx" ON "SignalEvent" ("signalId");
CREATE INDEX IF NOT EXISTS "SignalEvent_eventType_idx" ON "SignalEvent" ("eventType");

-- Kept for future use. The backtest/historical-replay feature was dropped in
-- the Python rewrite, but the table stays so an existing database keeps its
-- history and a future runner can write to it again.
CREATE TABLE IF NOT EXISTS "BacktestRun" (
    "id"         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "startedAt"  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "rangeStart" TIMESTAMP(3) NOT NULL,
    "rangeEnd"   TIMESTAMP(3) NOT NULL,
    "results"    TEXT NOT NULL
);

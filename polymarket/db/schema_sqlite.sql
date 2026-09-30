-- Local SQLite schema (same logical tables as Neon/Postgres schema.sql).
-- Applied automatically when DATABASE_URL=file:... or SQLITE_PATH is set.

CREATE TABLE IF NOT EXISTS Market (
    id          TEXT PRIMARY KEY,
    conditionId TEXT NOT NULL UNIQUE,
    asset       TEXT NOT NULL,
    priceToBeat REAL NOT NULL,
    openTime    TEXT NOT NULL,
    closeTime   TEXT NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0,
    outcome     TEXT
);

CREATE INDEX IF NOT EXISTS Market_openTime_idx ON Market (openTime);

CREATE TABLE IF NOT EXISTS Signal (
    id             TEXT PRIMARY KEY,
    marketId       TEXT NOT NULL REFERENCES Market (id) ON DELETE RESTRICT,
    strategyId     TEXT NOT NULL,
    direction      TEXT NOT NULL,
    confidence     REAL,
    entryPrice     REAL,
    entryCostUsd   REAL,
    createdAt      TEXT NOT NULL DEFAULT (datetime('now')),
    won            INTEGER,
    closedAt       TEXT,
    exitPrice      REAL,
    realizedPnlUsd REAL,
    exitReason     TEXT,
    result         TEXT
);

CREATE INDEX IF NOT EXISTS Signal_strategyId_idx ON Signal (strategyId);
CREATE INDEX IF NOT EXISTS Signal_marketId_idx ON Signal (marketId);

CREATE TABLE IF NOT EXISTS SignalEvent (
    id             TEXT PRIMARY KEY,
    signalId       TEXT NOT NULL REFERENCES Signal (id) ON DELETE CASCADE,
    eventType      TEXT NOT NULL,
    price          REAL,
    quantity       REAL,
    realizedPnlUsd REAL DEFAULT 0,
    note           TEXT,
    createdAt      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS SignalEvent_signalId_idx ON SignalEvent (signalId);
CREATE INDEX IF NOT EXISTS SignalEvent_eventType_idx ON SignalEvent (eventType);

CREATE TABLE IF NOT EXISTS BacktestRun (
    id         TEXT PRIMARY KEY,
    startedAt  TEXT NOT NULL DEFAULT (datetime('now')),
    rangeStart TEXT NOT NULL,
    rangeEnd   TEXT NOT NULL,
    results    TEXT NOT NULL
);

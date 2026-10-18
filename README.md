# BTC 5-Minute Strategy Board

Watches Polymarket's 5-minute BTC Up/Down markets live, runs nine rule-based
strategies against the real Chainlink price feed and the real CLOB order book,
and paper-trades each one with a $1,000 bankroll so you can see which rules
would actually make money. Optionally mirrors one strategy's trades onto a real
Polymarket account. A simulation page replays a recent resolved window (or
synthetic data) tick-by-tick through the same strategies.

One Python process, one port, no framework. A plain HTML/CSS/JS frontend with
no build step.

```bash
cp .env.example .env        # optional -- it runs with no .env at all
docker compose up --watch   # http://localhost:8000
```

## Pages

| Route | What it shows |
| --- | --- |
| `/` | Home — intro, live market embed, strategy explainer |
| `/board` | Live chart, spatial strategy board, copy trading |
| `/leaderboard` | Paper standings, sort/filter, trade ledgers |
| `/simulation` | Play/pause/scrub over a historical or synthetic window |
| `/active` | Redirects to `/board` (bookmark compat) |
| `/strategy` | Redirects to `/` (bookmark compat) |

## What you get

- **Status bar** — connection, time left, strike, live spot, real bid/ask.
- **Price chart** — TradingView lightweight-charts; green above strike, red below.
- **Spatial strategy board** — YES/NO zones; confidence pushes boxes from the baseline.
- **Strategy explainer** — one card per book with call, why, and paper P&L.
- **Leaderboard** — ranked cash, window/total P&L, win/loss, expandable ledgers.
- **Copy trading** — env keys + red confirm; $500 max stake enforced server-side.
- **Simulation** — `/api/backtest` loads a window; strategies stay server-side.

Every data feed is public — no API keys:

| Feed | What it provides |
| --- | --- |
| Gamma API (`gamma-api.polymarket.com`) | Market discovery via `btc-updown-5m-{timestamp}` |
| RTDS WebSocket (`ws-live-data.polymarket.com`) | Chainlink BTC/USD + ETH/USD |
| CLOB WebSocket + REST (`clob.polymarket.com`) | Live order book + historical token prices |
| Binance klines REST | 1-second BTC path for simulation replay |

## Running it

### Docker (primary)

```bash
docker compose up --watch
```

### uv (fallback, no Docker)

```bash
uv sync
uv run polymarket/server.py
```

Same `.env`, same port. `uv run pytest` runs the tests.

## Architecture

```
Gamma discovery ─┐
Chainlink RTDS ──┼─→ snapshot ─→ market state ─→ 9 strategies ─┬─→ paper trading ─→ copy trading
CLOB order book ─┘                                             ├─→ browsers (WebSocket)
                                                               └─→ SQLite or Neon (signal changes)

GET /api/backtest ─→ historical | synthetic ─→ per-tick signals for /simulation
```

- `polymarket/server.py` — HTTP (static + `/api/backtest` + `/healthz`) and WS `/ws` on one port.
- `polymarket/feed/` — Chainlink, CLOB, Gamma, historical + synthetic windows.
- `polymarket/strategies/` — `evaluate(snapshot, history) -> Signal`.
- `polymarket/engine/` — runner, paper trading, copy trader, backtest.
- `polymarket/db/` — optional SQLite or Neon; Prisma-compatible table names on Postgres.
- `polymarket/static/` — multi-page HTML/CSS/JS, no build step.

**Nine strategies, eleven books.** Lottery runs as &lt;5¢ / &lt;30¢ / &lt;40¢.

**The browser never polls the live board.** The server pushes ticks over WebSocket.
Simulation uses `GET /api/backtest` once per window load; scrubbing uses precomputed
per-tick signals so strategy logic stays in Python.

**Database is optional.** Default `DATABASE_URL=file:./dev.db` uses SQLite. Set
`NEON_DATABASE_URL` to use Postgres instead. With neither, the board runs in memory.

## Copy trading with real money

Off by default until credentials are in `.env` and copying is enabled in the UI
(or `COPY_TRADING_ENABLED=true`).

```bash
POLYMARKET_PRIVATE_KEY="0x..."
POLYMARKET_FUNDER_ADDRESS="0x..."
POLYMARKET_SIGNATURE_TYPE="1"
```

Safety rails: keys env-only, confirm click, $500 max per trade, FOK market orders
via `py-clob-client`.

## Tests

```bash
uv run pytest
```

## Deploying (Render)

This is an always-on process (feeds + WebSocket). Deploy as a **Render Web Service**
from the Dockerfile. Vercel serverless is not a fit for the backend.

1. Connect the repo on Render.
2. Use the included `render.yaml` or set health check path `/healthz`.
3. Set env vars (`NEON_DATABASE_URL` optional; copy-trading vars optional).

## Licence

MIT (inherited from the original project).

"""One process, one port: static frontend + live WebSocket.

No web framework. `websockets` handles the socket, and its `process_request`
hook answers plain HTTP requests off the same listener, so the dashboard and
the live feed share a single port with nothing but the standard library and
`websockets` in between.

    GET /                 -> static/index.html (home)
    GET /board, /leaderboard, /simulation -> static pages
    GET /active           -> redirect to /board
    GET /strategy         -> redirect to / (strategies live on home)
    GET /api/backtest     -> historical or synthetic window + per-tick signals
    GET /js/..., /css/... -> static files
    GET /healthz          -> plaintext ok
    WS  /ws               -> live JSON snapshots, and copy-trading commands back

Run it with `uv run polymarket/server.py` or `docker compose up --watch`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import signal
import sys
from http import HTTPStatus
from pathlib import Path
from typing import Optional, Union

# Allow `python polymarket/server.py` as well as `python -m polymarket.server`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from websockets.asyncio.server import ServerConnection, serve  # noqa: E402
from websockets.datastructures import Headers  # noqa: E402
from websockets.http11 import Response  # noqa: E402

from polymarket.engine.backtest import build_backtest_payload  # noqa: E402
from polymarket.engine.copy_trading import copy_trader  # noqa: E402
from polymarket.engine.runner import runner  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
WS_PATH = "/ws"
BACKTEST_PATH = "/api/backtest"

log = logging.getLogger("server")


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------


def _resolve_static(path: str) -> Optional[Path]:
    """Maps a URL path to a file inside static/, or None if it escapes."""
    clean = path.split("?", 1)[0].split("#", 1)[0]
    if clean in ("", "/"):
        clean = "/index.html"
    candidate = (STATIC_DIR / clean.lstrip("/")).resolve()
    try:
        candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
        return None  # directory traversal attempt
    if candidate.is_dir():
        candidate = candidate / "index.html"
    return candidate if candidate.is_file() else None


def _response(
    status: HTTPStatus,
    body: bytes,
    content_type: str,
    extra_headers: Optional[list[tuple[str, str]]] = None,
) -> Response:
    headers_list: list[tuple[str, str]] = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-cache"),
    ]
    if extra_headers:
        headers_list.extend(extra_headers)
    headers = Headers(headers_list)
    return Response(status.value, status.phrase, headers, body)


async def process_request(
    connection: ServerConnection, request
) -> Union[Response, None]:
    """Answers plain HTTP; returning None lets the WebSocket upgrade proceed."""
    path = request.path.split("?", 1)[0]

    if path == WS_PATH:
        return None

    if path == "/healthz":
        return _response(HTTPStatus.OK, b"ok", "text/plain; charset=utf-8")

    if path == "/active":
        return _response(
            HTTPStatus.FOUND,
            b"",
            "text/plain; charset=utf-8",
            extra_headers=[("Location", "/board")],
        )

    if path == "/strategy" or path == "/strategy/":
        return _response(
            HTTPStatus.FOUND,
            b"",
            "text/plain; charset=utf-8",
            extra_headers=[("Location", "/")],
        )

    if path == BACKTEST_PATH:
        try:
            payload = await build_backtest_payload()
            body = json.dumps(payload).encode("utf-8")
            return _response(HTTPStatus.OK, body, "application/json; charset=utf-8")
        except Exception as err:  # noqa: BLE001
            log.exception("backtest failed: %s", err)
            body = json.dumps({"error": str(err)}).encode("utf-8")
            return _response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                body,
                "application/json; charset=utf-8",
            )

    target = _resolve_static(path)
    if target is None:
        return _response(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")

    content_type, _ = mimetypes.guess_type(str(target))
    if content_type is None:
        content_type = "application/octet-stream"
    if content_type.startswith("text/") or content_type == "application/javascript":
        content_type = f"{content_type}; charset=utf-8"
    return _response(HTTPStatus.OK, target.read_bytes(), content_type)


# ---------------------------------------------------------------------------
# WebSocket fan-out
# ---------------------------------------------------------------------------

_clients: set[ServerConnection] = set()


async def _broadcast(payload: dict) -> None:
    if not _clients:
        return
    message = json.dumps(payload)
    for client in list(_clients):
        try:
            await client.send(message)
        except Exception:  # noqa: BLE001 -- a dropped client is not an error
            _clients.discard(client)


async def _handle_client_message(connection: ServerConnection, raw: str) -> None:
    """The browser's only upstream channel: copy-trading configuration.

    Credentials themselves never travel this way -- they are read server-side
    from .env and nothing here can set them. This mirrors POST /api/copy from
    the original app; it rides the existing socket so the process needs just
    one port.
    """
    try:
        message = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(message, dict) or message.get("type") != "copy_config":
        return

    enabled = message.get("enabled")
    strategy_id = message.get("strategyId")
    stake_usd = message.get("stakeUsd")

    status = copy_trader.set_config(
        enabled=enabled if isinstance(enabled, bool) else None,
        strategy_id=strategy_id if isinstance(strategy_id, str) else None,
        stake_usd=float(stake_usd) if isinstance(stake_usd, (int, float)) else None,
    )
    await connection.send(json.dumps({"type": "copy", "copy": status}))


async def ws_handler(connection: ServerConnection) -> None:
    _clients.add(connection)
    log.info("browser connected (%d live)", len(_clients))
    try:
        # First message carries the full window history so the chart can draw
        # the whole window immediately; later messages are deltas.
        initial = runner.build_payload(include_history=True)
        if initial is not None:
            await connection.send(json.dumps(initial))
        else:
            await connection.send(json.dumps({"type": "waiting"}))

        async for raw in connection:
            await _handle_client_message(connection, raw)
    except Exception:  # noqa: BLE001 -- normal disconnects land here too
        pass
    finally:
        _clients.discard(connection)
        log.info("browser disconnected (%d live)", len(_clients))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    runner.on_broadcast(_broadcast)

    async with serve(
        ws_handler,
        host,
        port,
        process_request=process_request,
        ping_interval=20,
    ):
        log.info("board on http://localhost:%d", port)
        await runner.start()

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass  # Windows
        await stop.wait()

        log.info("shutting down")
        await runner.stop()


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

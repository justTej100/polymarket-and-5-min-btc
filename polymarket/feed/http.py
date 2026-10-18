"""Shared HTTP GET for public Polymarket / Binance REST.

Cloudflare in front of gamma-api (and sometimes clob) returns 403 when the
request has no User-Agent -- Python's urllib default is empty. Always send a
browser-like UA + Accept.
"""

from __future__ import annotations

import json
import urllib.request

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (compatible; btc-strategy-board/0.1; "
        "+https://github.com/justTej100/polymarket-and-5-min-btc)"
    ),
}


def get_json(url: str, timeout: float = 10) -> object:
    request = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"request failed: {response.status} for {url}")
        return json.loads(response.read().decode("utf-8"))

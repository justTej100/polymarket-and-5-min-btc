"""Copy trading -- mirrors one strategy's paper trades onto a REAL Polymarket
account with REAL money, via Polymarket's official Python SDK.

Port of lib/trading/copyTrader.ts (@polymarket/clob-client -> py-clob-client).

Credentials come from .env only, never from the browser:
  POLYMARKET_PRIVATE_KEY     -- exported from Polymarket: profile -> settings
                                -> Export private key (or your own wallet key)
  POLYMARKET_FUNDER_ADDRESS  -- your Polymarket deposit/profile address
                                (the one that holds your USDC)
  POLYMARKET_SIGNATURE_TYPE  -- 1 = email/Magic login (default),
                                2 = browser-wallet login, 0 = raw EOA

Even with credentials present, copying stays OFF until it's switched on from
the dashboard (or COPY_TRADING_ENABLED=true). Buys are market orders for
COPY_STAKE_USD dollars; sells close whatever the copier bought. Wins and
losses settle on-chain automatically when the market resolves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from ..strategies import STRATEGIES, STRATEGIES_BY_ID
from .paper_trading import PaperTrade, paper_engine

CLOB_HOST = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137
ORDER_LOG_LIMIT = 40
MIN_STAKE_USD = 1
MAX_STAKE_USD = 500  # hard cap, whatever the dashboard asks for

log = logging.getLogger("copy")


@dataclass
class RealPosition:
    token_id: str
    side: str  # "UP" | "DOWN"
    shares: float


@dataclass
class EnvCreds:
    private_key: str
    funder: str
    signature_type: int


def env_creds() -> Optional[EnvCreds]:
    private_key = (os.environ.get("POLYMARKET_PRIVATE_KEY") or "").strip()
    funder = (os.environ.get("POLYMARKET_FUNDER_ADDRESS") or "").strip()
    if not private_key or not funder:
        return None
    if not private_key.startswith("0x"):
        private_key = f"0x{private_key}"
    try:
        signature_type = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE") or "1")
    except ValueError:
        signature_type = 1
    return EnvCreds(private_key=private_key, funder=funder, signature_type=signature_type)


class CopyTrader:
    def __init__(self) -> None:
        self._enabled = os.environ.get("COPY_TRADING_ENABLED") == "true"
        self._strategy_id = os.environ.get("COPY_STRATEGY_ID") or STRATEGIES[0].id
        try:
            self._stake_usd = float(os.environ.get("COPY_STAKE_USD") or "5")
        except ValueError:
            self._stake_usd = 5.0
        self._client = None
        self._client_lock = asyncio.Lock()
        self._address: Optional[str] = None
        self._orders: list[dict] = []
        self._positions: list[RealPosition] = []
        self._last_error: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        """Subscribes to the paper engine. Called once, from the running loop."""
        self._loop = loop
        paper_engine.on_trade(self._schedule_mirror)

    def _schedule_mirror(self, trade: PaperTrade) -> None:
        # The paper engine is synchronous; real orders are not. Hand off to
        # the loop so a slow exchange round-trip can never stall the feed.
        if self._loop is None:
            return
        if not self._enabled or trade.strategy_id != self._strategy_id:
            return
        self._loop.create_task(self._safe_mirror(trade))

    async def _safe_mirror(self, trade: PaperTrade) -> None:
        try:
            await self._on_paper_trade(trade)
        except Exception as err:  # noqa: BLE001
            self._last_error = str(err)
            log.error("trade mirror failed: %s", err)

    # -- config --------------------------------------------------------------

    def get_status(self) -> dict:
        strategy = STRATEGIES_BY_ID.get(self._strategy_id) or STRATEGIES[0]
        available = env_creds() is not None
        return {
            "available": available,  # credentials present in .env
            "enabled": self._enabled and available,
            "strategyId": strategy.id,
            "strategyName": strategy.name,
            "stakeUsd": self._stake_usd,
            "maxStakeUsd": MAX_STAKE_USD,
            "address": self._address,
            "orders": self._orders[:ORDER_LOG_LIMIT],
            "lastError": self._last_error,
            "strategies": [{"id": s.id, "name": s.name} for s in STRATEGIES],
        }

    def set_config(
        self,
        enabled: Optional[bool] = None,
        strategy_id: Optional[str] = None,
        stake_usd: Optional[float] = None,
    ) -> dict:
        if strategy_id and strategy_id in STRATEGIES_BY_ID:
            self._strategy_id = strategy_id
        if stake_usd is not None and stake_usd == stake_usd:  # not NaN
            self._stake_usd = min(MAX_STAKE_USD, max(MIN_STAKE_USD, float(stake_usd)))
        if enabled is not None:
            self._enabled = bool(enabled) and env_creds() is not None
            if enabled and env_creds() is None:
                self._last_error = (
                    "Add POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER_ADDRESS to .env, "
                    "then restart."
                )
            elif enabled:
                log.warning(
                    "copy trading ENABLED -- mirroring %s with real money at $%.2f/trade",
                    self._strategy_id,
                    self._stake_usd,
                )
            else:
                log.info("copy trading disabled")
        return self.get_status()

    # -- CLOB client (lazy, created on the first real order) -----------------

    async def _get_client(self):
        if self._client is not None:
            return self._client

        async with self._client_lock:
            if self._client is not None:
                return self._client

            creds = env_creds()
            if creds is None:
                raise RuntimeError("Polymarket credentials missing from .env")

            self._client = await asyncio.to_thread(_build_client, creds)
            self._address = await asyncio.to_thread(self._client.get_address)
            log.info("connected to Polymarket as %s", self._address)
            return self._client

    # -- mirroring -----------------------------------------------------------

    def _log_order(self, entry: dict) -> None:
        self._orders.insert(0, entry)
        if len(self._orders) > ORDER_LOG_LIMIT:
            self._orders.pop()

    async def _on_paper_trade(self, trade: PaperTrade) -> None:
        if not self._enabled or trade.strategy_id != self._strategy_id:
            return
        # WIN/LOSS are window resolutions -- real positions settle on-chain.
        if trade.action not in ("BUY", "SELL"):
            self._positions = []
            return

        from .runner import get_current_market  # local import avoids a cycle

        market = get_current_market()
        if market is None or market.condition_id != trade.condition_id:
            return

        token_id = market.up_token_id if trade.side == "UP" else market.down_token_id
        client = await self._get_client()

        if trade.action == "BUY":
            ok, detail = await asyncio.to_thread(
                _place_market_order, client, token_id, self._stake_usd, "BUY"
            )
            est_shares = self._stake_usd / max(trade.price, 0.01)
            if ok:
                self._positions.append(
                    RealPosition(token_id=token_id, side=trade.side, shares=est_shares)
                )
            self._last_error = None if ok else detail
            self._log_order(
                {
                    "timestamp": int(time.time() * 1000),
                    "action": "BUY",
                    "side": trade.side,
                    "detail": (
                        f"bought ~${self._stake_usd:.2f} of {trade.side} @ "
                        f"~{trade.price * 100:.1f}\u00a2 (copying {trade.strategy_name})"
                        if ok
                        else f"buy rejected: {detail}"
                    ),
                    "status": "ok" if ok else "error",
                }
            )
            return

        # SELL: close everything we bought on that side.
        held = [p for p in self._positions if p.token_id == token_id]
        if not held:
            return
        shares = sum(p.shares for p in held)

        ok, detail = await asyncio.to_thread(
            _place_market_order, client, token_id, int(shares * 100) / 100, "SELL"
        )
        if ok:
            self._positions = [p for p in self._positions if p.token_id != token_id]
        self._last_error = None if ok else detail
        self._log_order(
            {
                "timestamp": int(time.time() * 1000),
                "action": "SELL",
                "side": trade.side,
                "detail": (
                    f"sold ~{shares:.2f} {trade.side} shares @ ~{trade.price * 100:.1f}\u00a2 "
                    f"(copying {trade.strategy_name})"
                    if ok
                    else f"sell rejected: {detail}"
                ),
                "status": "ok" if ok else "error",
            }
        )


def _build_client(creds: EnvCreds):
    """Blocking: builds a signed, API-key-authenticated CLOB client."""
    from py_clob_client.client import ClobClient

    bootstrap = ClobClient(
        CLOB_HOST,
        chain_id=POLYGON_CHAIN_ID,
        key=creds.private_key,
        signature_type=creds.signature_type,
        funder=creds.funder,
    )
    api_creds = bootstrap.create_or_derive_api_creds()
    bootstrap.set_api_creds(api_creds)
    return bootstrap


def _place_market_order(client, token_id: str, amount: float, side: str) -> tuple[bool, str]:
    """Blocking: BUY amount is dollars, SELL amount is shares (SDK convention)."""
    from py_clob_client.clob_types import MarketOrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL

    order = client.create_market_order(
        MarketOrderArgs(
            token_id=token_id,
            amount=amount,
            side=BUY if side == "BUY" else SELL,
        )
    )
    response = client.post_order(order, OrderType.FOK)
    ok = not (isinstance(response, dict) and response.get("success") is False)
    if ok:
        return True, ""
    error = response.get("errorMsg") if isinstance(response, dict) else response
    return False, json.dumps(error) if not isinstance(error, str) else error


# One copy trader for the whole process, so nothing can double-place an order.
copy_trader = CopyTrader()

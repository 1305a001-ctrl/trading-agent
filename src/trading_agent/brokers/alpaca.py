"""Alpaca broker — REST API. Paper by default; `ALPACA_BASE_URL` flips to live.

Sign up at https://alpaca.markets — get key + secret from the dashboard.

Paper:  https://paper-api.alpaca.markets
Live:   https://api.alpaca.markets

Sizing uses Alpaca's `notional` parameter (USD amount, fractional shares ok).
Market orders only — `time_in_force=day`. Outside RTH the order queues until
market open; we poll for up to `ALPACA_FILL_TIMEOUT_SECONDS` and otherwise raise
so the trade is marked `rejected` rather than silently pending.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from trading_agent.models import Fill
from trading_agent.settings import settings

log = logging.getLogger(__name__)


class AlpacaBroker:
    name = "alpaca"

    def __init__(self) -> None:
        if not settings.alpaca_api_key or not settings.alpaca_secret:
            raise RuntimeError(
                "Alpaca broker requested but ALPACA_API_KEY / ALPACA_SECRET not set"
            )
        self._base = settings.alpaca_base_url.rstrip("/")
        self._headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret,
            "Content-Type": "application/json",
        }

    async def open(self, asset: str, direction: str, size_usd: float) -> Fill:
        side = "buy" if direction == "long" else "sell"
        order = await self._post("/v2/orders", {
            "symbol": asset,
            "notional": f"{size_usd:.2f}",
            "side": side,
            "type": "market",
            "time_in_force": "day",
        })
        filled = await self._poll_fill(order["id"])
        return Fill(
            broker_order_id=filled["id"],
            entry_price=float(filled["filled_avg_price"]),
            qty=float(filled["filled_qty"]),
            opened_at=_parse_iso(filled["filled_at"]),
        )

    async def close(self, broker_order_id: str, asset: str) -> float:
        # broker_order_id is the OPEN order id; closing goes by symbol
        del broker_order_id
        order = await self._delete(f"/v2/positions/{asset}")
        filled = await self._poll_fill(order["id"])
        return float(filled["filled_avg_price"])

    # ─── HTTP helpers ────────────────────────────────────────────────────────

    async def _post(self, path: str, body: dict) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{self._base}{path}", headers=self._headers, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"alpaca {path} {r.status_code}: {r.text}")
        return r.json()

    async def _delete(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.delete(f"{self._base}{path}", headers=self._headers)
        if r.status_code >= 400:
            raise RuntimeError(f"alpaca {path} {r.status_code}: {r.text}")
        return r.json()

    async def _get(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self._base}{path}", headers=self._headers)
        if r.status_code >= 400:
            raise RuntimeError(f"alpaca {path} {r.status_code}: {r.text}")
        return r.json()

    async def _poll_fill(self, order_id: str) -> dict[str, Any]:
        deadline_iters = max(1, settings.alpaca_fill_timeout_seconds)
        for _ in range(deadline_iters):
            o = await self._get(f"/v2/orders/{order_id}")
            status = o.get("status")
            if status == "filled":
                return o
            if status in {"canceled", "expired", "rejected"}:
                raise RuntimeError(
                    f"alpaca order {order_id} {status}: {o.get('reject_reason') or ''}"
                )
            await asyncio.sleep(1)
        raise RuntimeError(
            f"alpaca order {order_id} did not fill in {settings.alpaca_fill_timeout_seconds}s "
            f"(market closed? extended-hours not enabled)"
        )


def _parse_iso(s: str | None) -> datetime:
    if not s:
        return datetime.now(tz=None)
    # Alpaca returns 2024-01-01T00:00:00.000Z — Python's fromisoformat handles 3.11+
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

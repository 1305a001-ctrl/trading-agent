"""Paper broker — fills using live mid-prices, no real orders.

Records every "fill" as a fake broker_order_id (uuid). Used as the default
in v0.1 so we can validate the full pipeline (signal → decision → trade
→ position polling → close) without committing real capital.
"""
from datetime import UTC, datetime
from uuid import uuid4

from trading_agent.models import Fill
from trading_agent.prices import get_price


class PaperBroker:
    name = "paper"

    async def open(self, asset: str, direction: str, size_usd: float) -> Fill:
        price = await get_price(asset)
        if price is None or price <= 0:
            raise RuntimeError(f"paper broker: no price for {asset}")
        qty = size_usd / price
        return Fill(
            broker_order_id=f"paper-{uuid4()}",
            entry_price=price,
            qty=qty,
            opened_at=datetime.now(UTC),
        )

    async def close(self, broker_order_id: str, asset: str) -> float:
        price = await get_price(asset)
        if price is None or price <= 0:
            raise RuntimeError(f"paper broker: no price for {asset} on close")
        return price

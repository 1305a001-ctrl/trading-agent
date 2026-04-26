from typing import Protocol

from trading_agent.models import Fill


class Broker(Protocol):
    name: str

    async def open(self, asset: str, direction: str, size_usd: float) -> Fill: ...
    async def close(self, broker_order_id: str, asset: str) -> float:
        """Return exit price. May raise on failure."""
        ...

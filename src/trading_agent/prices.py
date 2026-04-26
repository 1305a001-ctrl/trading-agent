"""Price feed adapters for paper-broker fills + position polling.

Asset routing:
  - BTC, ETH, SOL, ... → Binance public ticker (no key needed)
  - NVDA, AAPL, ... US equities → Finnhub
  - KLSE / Bursa → not yet implemented (return None; KLSE trades will skip live polling)
"""
import logging

import httpx

from trading_agent.settings import settings

log = logging.getLogger(__name__)

CRYPTO = {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "MATIC", "DOT"}
US_EQUITIES = {"NVDA", "AAPL", "MSFT", "GOOG", "GOOGL", "META", "AMZN", "TSLA", "AMD"}


async def get_price(asset: str) -> float | None:
    a = asset.upper()
    try:
        if a in CRYPTO:
            return await _binance_price(a)
        if a in US_EQUITIES:
            return await _finnhub_price(a)
        log.warning("No price feed routed for asset %s", asset)
        return None
    except Exception as exc:  # noqa: BLE001
        log.error("Price fetch failed for %s: %s", asset, exc)
        return None


async def _binance_price(symbol: str) -> float | None:
    pair = f"{symbol}USDT"
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{settings.binance_base_url}/api/v3/ticker/price", params={"symbol": pair})
        r.raise_for_status()
        return float(r.json()["price"])


async def _finnhub_price(symbol: str) -> float | None:
    if not settings.finnhub_key:
        return None
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol, "token": settings.finnhub_key},
        )
        r.raise_for_status()
        data = r.json()
        # 'c' = current price; 0 means market closed / no quote
        price = data.get("c")
        return float(price) if price else None

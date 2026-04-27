"""Broker registry. New brokers register themselves here."""
import logging

from trading_agent.brokers.base import Broker
from trading_agent.brokers.paper import PaperBroker
from trading_agent.settings import settings

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type[Broker]] = {
    "paper": PaperBroker,
}

# Conditionally register Alpaca only if credentials are configured —
# avoids "broker not implemented" surprises when an env var is forgotten.
if settings.alpaca_api_key and settings.alpaca_secret:
    from trading_agent.brokers.alpaca import AlpacaBroker
    _REGISTRY["alpaca"] = AlpacaBroker
    log.info("Alpaca broker registered (base=%s)", settings.alpaca_base_url)


def get_broker(name: str) -> Broker:
    cls = _REGISTRY.get(name)
    if cls is None:
        available = sorted(_REGISTRY.keys())
        raise ValueError(
            f"Broker {name!r} not registered. Available: {available}. "
            f"For Alpaca, set ALPACA_API_KEY + ALPACA_SECRET."
        )
    return cls()

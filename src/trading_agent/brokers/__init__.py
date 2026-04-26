from trading_agent.brokers.base import Broker
from trading_agent.brokers.paper import PaperBroker

_REGISTRY: dict[str, type[Broker]] = {
    "paper": PaperBroker,
}


def get_broker(name: str) -> Broker:
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown broker: {name!r} (live brokers not yet wired in v0.1)")
    return cls()

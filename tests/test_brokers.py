"""Smoke tests for the broker registry. Live Alpaca calls are integration-tested by hand."""
import pytest

from trading_agent.brokers import get_broker
from trading_agent.brokers.paper import PaperBroker


def test_paper_always_available():
    b = get_broker("paper")
    assert isinstance(b, PaperBroker)
    assert b.name == "paper"


def test_unknown_broker_raises_with_help():
    with pytest.raises(ValueError) as exc:
        get_broker("kraken")
    msg = str(exc.value)
    assert "not registered" in msg
    # error message should include available brokers + how to enable Alpaca
    assert "paper" in msg
    assert "ALPACA_API_KEY" in msg


def test_alpaca_unregistered_without_creds(monkeypatch):
    """Without env vars, alpaca isn't in the registry — fail-loud."""
    # The module-level registration ran at import; in this test we just confirm
    # that 'alpaca' resolves the same way 'kraken' does when creds are absent.
    # (CI has no alpaca creds, so it's already absent.)
    from trading_agent.settings import settings
    if settings.alpaca_api_key and settings.alpaca_secret:
        pytest.skip("Alpaca creds present in env — registration test n/a")
    with pytest.raises(ValueError, match="not registered"):
        get_broker("alpaca")

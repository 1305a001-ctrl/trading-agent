from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from signals_contract import Signal

# Re-export Signal so consumers of this module's public surface keep working.
__all__ = ["Signal", "TradingRules", "TradeIntent", "Fill"]


class TradingRules(BaseModel):
    """Resolved per-trade rules.

    Fallback chain: agent_config → strategy.trading → settings defaults.
    """
    stop_loss_pct: float = Field(gt=0, lt=1)
    take_profit_pct: float = Field(gt=0, lt=1)
    time_stop_hours: int = Field(gt=0)
    size_usd: float = Field(gt=0)
    broker: Literal["paper", "alpaca", "binance", "ibkr"] = "paper"


class TradeIntent(BaseModel):
    """Decision output: what to place. Pre-fill, pre-broker."""
    signal_id: UUID
    agent_config_id: UUID
    agent_config_version: int
    asset: str
    direction: Literal["long", "short"]
    rules: TradingRules


class Fill(BaseModel):
    """Broker response after order placement."""
    broker_order_id: str
    entry_price: float
    qty: float
    opened_at: datetime

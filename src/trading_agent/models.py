import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class Signal(BaseModel):
    """Inbound signal from Redis (matches news-consolidator INTEGRATION.md)."""
    id: UUID
    strategy_id: UUID
    research_config_id: UUID
    strategy_git_sha: str
    research_config_version: int
    asset: str
    direction: Literal["long", "short", "neutral", "watch"]
    confidence: float = Field(ge=0.0, le=1.0)
    composite_risk_score: float | None = None
    risk_score: dict | None = None
    source_article_ids: list[UUID] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)
    published_at: datetime

    @field_validator("risk_score", "payload", mode="before")
    @classmethod
    def _parse_json_string(cls, v: Any) -> Any:
        """Tolerate publishers that double-encode JSONB as strings (e.g. ad-hoc psql republish)."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        return v


class TradingRules(BaseModel):
    """Resolved per-trade rules. Fallback chain: agent_config → strategy.trading → settings defaults."""
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

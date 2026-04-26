"""Postgres client for trading-agent. Uses asyncpg directly — no ORM."""
import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from trading_agent.settings import settings

log = logging.getLogger(__name__)


class DB:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("DB not connected — call connect() first")
        return self._pool

    async def connect(self) -> None:
        if not settings.aicore_db_url:
            raise RuntimeError("AICORE_DB_URL not set")
        self._pool = await asyncpg.create_pool(
            settings.aicore_db_url,
            min_size=1, max_size=5,
            init=_init_connection,
        )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    # ─── Reads ──────────────────────────────────────────────────────────────

    async def get_active_trading_config(self, asset: str) -> dict | None:
        """Return the most recent active trading agent_config whose slug matches `asset`.

        UI writes one config per asset, slug=asset symbol (e.g. 'BTC').
        """
        row = await self.pool.fetchrow(
            """
            SELECT id, version, config
            FROM agent_configs
            WHERE agent_type = 'trading'
              AND is_active = TRUE
              AND slug = $1
            ORDER BY version DESC, updated_at DESC
            LIMIT 1
            """,
            asset,
        )
        if not row:
            return None
        return {"id": row["id"], "version": row["version"], "config": row["config"]}

    async def get_strategy_trading_block(self, strategy_id: UUID) -> dict:
        """Return the strategy.frontmatter.trading block (or {} if absent)."""
        row = await self.pool.fetchrow(
            "SELECT frontmatter FROM strategies WHERE id = $1",
            strategy_id,
        )
        if not row:
            return {}
        return (row["frontmatter"] or {}).get("trading", {}) or {}

    async def open_position_size_usd(self) -> float:
        row = await self.pool.fetchrow(
            "SELECT COALESCE(SUM(size_usd), 0) AS total FROM trades "
            "WHERE status IN ('pending','open')"
        )
        return float(row["total"])

    async def open_count_for_asset(self, asset: str) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS n FROM trades "
            "WHERE asset = $1 AND status IN ('pending','open')",
            asset,
        )
        return int(row["n"])

    async def trades_today_for_asset(self, asset: str) -> int:
        """Count of trades opened in the last 24h for this asset."""
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS n FROM trades "
            "WHERE asset = $1 AND created_at > NOW() - INTERVAL '24 hours'",
            asset,
        )
        return int(row["n"])

    async def has_open_position_same_dir(self, asset: str, direction: str) -> bool:
        row = await self.pool.fetchrow(
            "SELECT 1 FROM trades WHERE asset = $1 AND direction = $2 "
            "AND status IN ('pending','open') LIMIT 1",
            asset, direction,
        )
        return row is not None

    async def open_trades(self) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            "SELECT * FROM trades WHERE status IN ('pending','open') ORDER BY opened_at"
        )

    # ─── Writes ─────────────────────────────────────────────────────────────

    async def insert_trade(self, intent_row: dict[str, Any]) -> UUID:
        row = await self.pool.fetchrow(
            """
            INSERT INTO trades
              (signal_id, agent_config_id, agent_config_version, asset, direction,
               broker, size_usd, take_profit_price, stop_loss_price,
               time_stop_at, status, metadata)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            RETURNING id
            """,
            intent_row["signal_id"],
            intent_row["agent_config_id"],
            intent_row["agent_config_version"],
            intent_row["asset"],
            intent_row["direction"],
            intent_row["broker"],
            intent_row["size_usd"],
            intent_row.get("take_profit_price"),
            intent_row.get("stop_loss_price"),
            intent_row.get("time_stop_at"),
            intent_row.get("status", "pending"),
            intent_row.get("metadata", {}),
        )
        return row["id"]

    async def fill_trade(self, trade_id: UUID, *, entry_price: float, qty: float,
                         broker_order_id: str, take_profit_price: float | None,
                         stop_loss_price: float | None, opened_at: datetime) -> None:
        await self.pool.execute(
            """
            UPDATE trades
               SET status = 'open',
                   broker_order_id = $2,
                   entry_price = $3,
                   qty = $4,
                   take_profit_price = COALESCE($5, take_profit_price),
                   stop_loss_price = COALESCE($6, stop_loss_price),
                   opened_at = $7
             WHERE id = $1
            """,
            trade_id, broker_order_id, entry_price, qty,
            take_profit_price, stop_loss_price, opened_at,
        )

    async def close_trade(self, trade_id: UUID, *, exit_price: float, pnl_usd: float,
                          close_reason: str, closed_at: datetime) -> None:
        await self.pool.execute(
            """
            UPDATE trades
               SET status = 'closed', exit_price = $2, pnl_usd = $3,
                   close_reason = $4, closed_at = $5
             WHERE id = $1
            """,
            trade_id, exit_price, pnl_usd, close_reason, closed_at,
        )

    async def reject_trade(self, trade_id: UUID, reason: str) -> None:
        await self.pool.execute(
            "UPDATE trades SET status = 'rejected', errors = errors || $2::jsonb WHERE id = $1",
            trade_id, [reason],
        )

    async def write_signal_outcome(self, *, signal_id: UUID, horizon: str, outcome: str,
                                   price_at_signal: float | None, price_at_eval: float | None,
                                   notes: str | None) -> None:
        pct = None
        if price_at_signal and price_at_eval and price_at_signal != 0:
            pct = (price_at_eval - price_at_signal) / price_at_signal
        await self.pool.execute(
            """
            INSERT INTO signal_outcomes
              (signal_id, evaluation_horizon, outcome,
               price_at_signal, price_at_evaluation, price_change_pct, notes)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            """,
            signal_id, horizon, outcome, price_at_signal, price_at_eval, pct, notes,
        )


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSONB codec so reads return dicts (matches news-consolidator pattern)."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


db = DB()

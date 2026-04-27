"""Trading agent daemon.

Runs two concurrent loops:
  1. signal_loop  — subscribes to Redis signals:trading + signals:critical,
                    evaluates each signal, opens trades that pass.
  2. position_loop — walks open positions every N seconds, closes on TP/SL/time-stop.
"""
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import redis.asyncio as aioredis
import sentry_sdk
import structlog

from trading_agent import alerts
from trading_agent.brokers import get_broker
from trading_agent.db import db
from trading_agent.decision import decide
from trading_agent.halt import is_halted
from trading_agent.models import Signal, TradeIntent
from trading_agent.positions import position_loop
from trading_agent.settings import settings

log = logging.getLogger(__name__)


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.0)


async def _open_position(intent: TradeIntent, signal: Signal) -> None:
    """Insert pending row, place broker order, fill row, alert."""
    rules = intent.rules
    time_stop = datetime.now(UTC) + timedelta(hours=rules.time_stop_hours)

    trade_id = await db.insert_trade({
        "signal_id": intent.signal_id,
        "agent_config_id": intent.agent_config_id,
        "agent_config_version": intent.agent_config_version,
        "asset": intent.asset,
        "direction": intent.direction,
        "broker": rules.broker,
        "size_usd": rules.size_usd,
        "time_stop_at": time_stop,
        "metadata": {
            "confidence": signal.confidence,
            "composite_risk_score": signal.composite_risk_score,
            "strategy_git_sha": signal.strategy_git_sha,
        },
    })

    broker = get_broker(rules.broker)
    try:
        fill = await broker.open(intent.asset, intent.direction, rules.size_usd)
    except Exception as exc:
        log.error("Broker open failed for %s: %s", trade_id, exc)
        await db.reject_trade(trade_id, f"broker open failed: {exc}")
        return

    if intent.direction == "long":
        tp = fill.entry_price * (1 + rules.take_profit_pct)
        sl = fill.entry_price * (1 - rules.stop_loss_pct)
    else:
        tp = fill.entry_price * (1 - rules.take_profit_pct)
        sl = fill.entry_price * (1 + rules.stop_loss_pct)

    await db.fill_trade(
        trade_id,
        entry_price=fill.entry_price,
        qty=fill.qty,
        broker_order_id=fill.broker_order_id,
        take_profit_price=tp,
        stop_loss_price=sl,
        opened_at=fill.opened_at,
    )

    await alerts.telegram(alerts.format_open(
        asset=intent.asset,
        direction=intent.direction,
        size_usd=rules.size_usd,
        entry=fill.entry_price,
        tp=tp,
        sl=sl,
        broker=rules.broker,
        confidence=signal.confidence,
    ))
    log.info(
        "Opened %s %s size=$%.0f entry=%.4f tp=%.4f sl=%.4f broker=%s",
        intent.asset, intent.direction, rules.size_usd, fill.entry_price, tp, sl, rules.broker,
    )


async def _handle_signal(signal: Signal) -> None:
    halted = await is_halted()

    agent_config = await db.get_active_trading_config(signal.asset)
    strategy_trading = await db.get_strategy_trading_block(signal.strategy_id)
    open_total = await db.open_position_size_usd()
    open_count = await db.open_count_for_asset(signal.asset)
    trades_today = await db.trades_today_for_asset(signal.asset)
    has_dup = (
        await db.has_open_position_same_dir(signal.asset, signal.direction)
        if signal.direction in ("long", "short") else False
    )

    intent, skip = decide(
        signal=signal,
        agent_config=agent_config,
        strategy_trading=strategy_trading,
        open_total_usd=open_total,
        open_count_asset=open_count,
        trades_today_asset=trades_today,
        has_open_same_direction=has_dup,
        halt=halted,
    )
    if intent is None:
        log.info("Skipped signal %s (%s %s conf=%.2f): %s",
                 signal.id, signal.asset, signal.direction, signal.confidence, skip)
        return

    await _open_position(intent, signal)


async def signal_loop() -> None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe("signals:trading", "signals:critical")
    log.info("Subscribed to signals:trading + signals:critical")

    seen_ids: set[UUID] = set()  # in-memory dedup for criticals duplicated on trading channel
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            raw = json.loads(message["data"])
            signal = Signal.model_validate(raw)
        except Exception as exc:
            log.error("Bad signal payload on %s: %s", message.get("channel"), exc)
            continue

        if signal.id in seen_ids:
            continue
        seen_ids.add(signal.id)
        if len(seen_ids) > 1000:
            seen_ids.clear()

        try:
            await _handle_signal(signal)
        except Exception:
            log.exception("Failed to handle signal %s", signal.id)


async def main() -> None:
    _setup_logging()
    log.info("trading-agent starting (default broker=%s, halt=%s)",
             settings.default_broker, settings.trading_agent_halt)
    await db.connect()
    try:
        await asyncio.gather(signal_loop(), position_loop())
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Background loop: walks every open position, closes on TP/SL/time-stop."""
import asyncio
import logging
from datetime import UTC, datetime

from trading_agent import alerts
from trading_agent.brokers import get_broker
from trading_agent.db import db
from trading_agent.prices import get_price
from trading_agent.settings import settings

log = logging.getLogger(__name__)


async def _close(trade, *, exit_price: float, reason: str) -> None:
    pnl_pct = (exit_price - trade["entry_price"]) / trade["entry_price"]
    if trade["direction"] == "short":
        pnl_pct = -pnl_pct
    pnl_usd = trade["size_usd"] * pnl_pct
    closed_at = datetime.now(UTC)

    await db.close_trade(
        trade["id"],
        exit_price=exit_price,
        pnl_usd=pnl_usd,
        close_reason=reason,
        closed_at=closed_at,
    )

    # Outcome row for consistency_scores downstream calc
    await db.write_signal_outcome(
        signal_id=trade["signal_id"],
        horizon=f"{(closed_at - trade['opened_at']).total_seconds() / 3600:.1f}h",
        outcome="win" if pnl_usd > 0 else ("loss" if pnl_usd < 0 else "flat"),
        price_at_signal=trade["entry_price"],
        price_at_eval=exit_price,
        notes=f"closed by {reason} (paper)",
    )

    await alerts.telegram(alerts.format_close(
        asset=trade["asset"],
        direction=trade["direction"],
        entry=trade["entry_price"],
        exit_price=exit_price,
        pnl_usd=pnl_usd,
        reason=reason,
        broker=trade["broker"],
    ))
    log.info("Closed %s %s by %s pnl=$%.2f", trade["asset"], trade["direction"], reason, pnl_usd)


async def _check_one(trade) -> None:
    if trade["status"] != "open" or trade["entry_price"] is None:
        return

    # Time stop?
    if trade["time_stop_at"] and datetime.now(UTC) >= trade["time_stop_at"]:
        broker = get_broker(trade["broker"])
        try:
            exit_price = await broker.close(trade["broker_order_id"], trade["asset"])
        except Exception as exc:
            log.error("close failed (time_stop) for %s: %s", trade["id"], exc)
            return
        await _close(trade, exit_price=exit_price, reason="time_stop")
        return

    # Need a current price for TP/SL check
    price = await get_price(trade["asset"])
    if price is None:
        return  # no feed for this asset, skip silently

    direction = trade["direction"]
    tp = trade["take_profit_price"]
    sl = trade["stop_loss_price"]

    hit = None
    if direction == "long":
        if tp and price >= tp:
            hit = "tp"
        elif sl and price <= sl:
            hit = "sl"
    else:  # short
        if tp and price <= tp:
            hit = "tp"
        elif sl and price >= sl:
            hit = "sl"

    if hit:
        broker = get_broker(trade["broker"])
        try:
            exit_price = await broker.close(trade["broker_order_id"], trade["asset"])
        except Exception as exc:
            log.error("close failed (%s) for %s: %s", hit, trade["id"], exc)
            return
        await _close(trade, exit_price=exit_price, reason=hit)


async def position_loop() -> None:
    log.info("Position polling loop started (every %ds)", settings.poll_interval_seconds)
    while True:
        try:
            trades = await db.open_trades()
            for t in trades:
                await _check_one(t)
        except Exception as exc:  # noqa: BLE001
            log.exception("position_loop iteration failed: %s", exc)
        await asyncio.sleep(settings.poll_interval_seconds)

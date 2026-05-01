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

    # Outcome row for consistency_scores downstream calc.
    # We use horizon='trade_close' to distinguish actual paper-trade closes
    # from outcome-scorer's horizon-based price-only evaluations (4h/1d/7d).
    # Aggregation in consistency_scores treats them as separate buckets.
    duration_h = (closed_at - trade["opened_at"]).total_seconds() / 3600
    await db.write_signal_outcome(
        signal_id=trade["signal_id"],
        horizon="trade_close",
        outcome="win" if pnl_usd > 0 else ("loss" if pnl_usd < 0 else "flat"),
        price_at_signal=trade["entry_price"],
        price_at_eval=exit_price,
        notes=f"closed by {reason} after {duration_h:.1f}h (paper, pnl=${pnl_usd:+.2f})",
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


def _trailing_stop_check(trade, current_price: float) -> tuple[float, bool]:
    """Compute new peak + whether trailing-stop should fire.

    Returns (new_peak, trailing_hit). Pure function, testable.
    Only fires if peak has exceeded entry (i.e., position went profitable at some
    point). When position is still underwater from entry, SL handles the downside
    and trailing stop does not interfere.
    """
    metadata = trade.get("metadata") or {}
    trailing_pct = metadata.get("trailing_stop_pct")
    if trailing_pct is None:
        return trade["entry_price"], False

    peak = metadata.get("peak_price") or trade["entry_price"]
    direction = trade["direction"]
    entry = trade["entry_price"]

    if direction == "long":
        new_peak = max(peak, current_price)
        threshold = new_peak * (1 - float(trailing_pct))
        # Only fire if peak exceeded entry AND price retraced past threshold
        trailing_hit = new_peak > entry and current_price <= threshold
    else:  # short — peak is the LOWEST price
        new_peak = min(peak, current_price)
        threshold = new_peak * (1 + float(trailing_pct))
        trailing_hit = new_peak < entry and current_price >= threshold

    return new_peak, trailing_hit


async def _check_one(trade) -> None:
    if trade["status"] != "open" or trade["entry_price"] is None:
        return

    # Time stop comes first — independent of price feed availability.
    if trade["time_stop_at"] and datetime.now(UTC) >= trade["time_stop_at"]:
        broker = get_broker(trade["broker"])
        try:
            exit_price = await broker.close(trade["broker_order_id"], trade["asset"])
        except Exception as exc:
            log.error("close failed (time_stop) for %s: %s", trade["id"], exc)
            return
        await _close(trade, exit_price=exit_price, reason="time_stop")
        return

    # Need a current price for trailing-stop + TP/SL checks.
    price = await get_price(trade["asset"])
    if price is None:
        return  # no feed for this asset, skip silently

    # Trailing stop check (only active if metadata.trailing_stop_pct set)
    new_peak, trailing_hit = _trailing_stop_check(trade, price)
    metadata = trade.get("metadata") or {}
    if metadata.get("trailing_stop_pct") is not None:
        # Persist peak update if it changed (no-op if same)
        existing_peak = metadata.get("peak_price") or trade["entry_price"]
        if new_peak != existing_peak:
            await db.update_trade_peak(trade["id"], new_peak)
        if trailing_hit:
            broker = get_broker(trade["broker"])
            try:
                exit_price = await broker.close(trade["broker_order_id"], trade["asset"])
            except Exception as exc:
                log.error("close failed (trailing_stop) for %s: %s", trade["id"], exc)
                return
            await _close(trade, exit_price=exit_price, reason="trailing_stop")
            return

    # Standard TP/SL check
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

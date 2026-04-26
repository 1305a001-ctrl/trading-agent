"""Telegram alert sender. No-ops cleanly when bot token / chat id absent."""
import logging

import httpx

from trading_agent.settings import settings

log = logging.getLogger(__name__)


async def telegram(text: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.debug("Telegram alert skipped (no creds): %s", text[:80])
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            await c.post(url, json={
                "chat_id": settings.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
    except Exception as exc:  # noqa: BLE001
        log.error("Telegram alert failed: %s", exc)


def format_open(*, asset: str, direction: str, size_usd: float, entry: float,
                tp: float | None, sl: float | None, broker: str, confidence: float) -> str:
    lines = [
        f"<b>📈 OPEN</b> {asset} {direction.upper()}",
        f"size ${size_usd:.0f} @ {entry:.4f}",
    ]
    if tp is not None and sl is not None:
        lines.append(f"TP {tp:.4f} | SL {sl:.4f}")
    lines.append(f"broker={broker} conf={confidence:.2f}")
    return "\n".join(lines)


def format_close(*, asset: str, direction: str, entry: float, exit_price: float,
                 pnl_usd: float, reason: str, broker: str) -> str:
    pct = (exit_price - entry) / entry if entry else 0.0
    if direction == "short":
        pct = -pct
    sign = "🟢" if pnl_usd >= 0 else "🔴"
    return (
        f"<b>{sign} CLOSE</b> {asset} {direction.upper()} ({reason})\n"
        f"entry {entry:.4f} → exit {exit_price:.4f} ({pct*100:+.2f}%)\n"
        f"pnl ${pnl_usd:+.2f}  broker={broker}"
    )

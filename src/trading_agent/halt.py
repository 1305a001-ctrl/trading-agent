"""Cross-agent kill switch.

Reads `system:halt` from Redis. When set to anything truthy, the agent stops
opening new positions / making outbound calls. Existing positions still
exit normally on TP/SL/time-stop.

Cached for 5 seconds so we don't hammer Redis on every signal.

The KEY is shared across trading-agent + poly-agent + pa-agent. pa-agent's
/halt and /resume Telegram commands set/clear it.
"""
import logging
import time

import redis.asyncio as aioredis

from trading_agent.settings import settings

log = logging.getLogger(__name__)

KEY = "system:halt"
CACHE_TTL_S = 5

_state: dict = {"halted": False, "ts": 0.0, "client": None}


async def is_halted() -> bool:
    """Returns True if the system is in halt mode (env flag OR Redis flag)."""
    if settings.trading_agent_halt:
        return True

    now = time.monotonic()
    if now - _state["ts"] < CACHE_TTL_S:
        return _state["halted"]

    try:
        if _state["client"] is None:
            _state["client"] = aioredis.from_url(settings.redis_url, decode_responses=True)
        v = await _state["client"].get(KEY)
        halted = bool(v) and v not in ("0", "false", "False", "")
    except Exception as exc:  # noqa: BLE001
        log.warning("halt check failed: %s — assuming NOT halted", exc)
        halted = False

    _state["halted"] = halted
    _state["ts"] = now
    return halted

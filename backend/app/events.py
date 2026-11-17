"""Recent buyer activity for the dashboard: a capped Redis list, newest first.

Runs of "rejected" (sold out) events are merged into one entry; see lua/push_event.lua.
"""
import json
import time

from .context import Context
from .sales import Sale

MAX_EVENTS = 50
EVENT_TYPES = ("waiting", "reserved", "confirmed", "expired", "rejected")


async def record(ctx: Context, sale: Sale, buyer_id: str, event: str, units: int = 1) -> None:
    """Never raises: the activity feed must not be able to break checkout."""
    if not ctx.settings.activity_log:
        return
    try:
        now = time.time()
        entry = json.dumps({"buyer_id": buyer_id, "event": event, "units": units, "ts": now})
        await ctx.scripts.push_event(
            keys=[f"{sale.keys.prefix}events"], args=[entry, MAX_EVENTS, event, now, buyer_id]
        )
    except Exception:
        pass


async def recent(ctx: Context, sale: Sale, limit: int = 15) -> list[dict]:
    raw = await ctx.redis.lrange(f"{sale.keys.prefix}events", 0, max(limit, 1) - 1)
    return [json.loads(item) for item in raw]

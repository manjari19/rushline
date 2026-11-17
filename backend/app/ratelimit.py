"""Per-buyer sliding window rate limiting (the algorithm lives in lua/rate_limit.lua)."""
import time
import uuid

from fastapi import HTTPException

from .context import Context
from .sales import Sale


async def enforce_rate_limit(ctx: Context, sale: Sale, identity: str) -> None:
    s = ctx.settings
    allowed, retry_ms = await ctx.scripts.rate_limit(
        keys=[sale.keys.rate(identity)],
        args=[int(time.time() * 1000), int(s.rate_limit_window_seconds * 1000),
              s.rate_limit_max, uuid.uuid4().hex],
    )
    if not allowed:
        retry_s = max(1, -(-retry_ms // 1000))
        raise HTTPException(
            429,
            detail={"code": "rate_limited", "message": "Too many requests. Slow down a little."},
            headers={"Retry-After": str(retry_s)},
        )

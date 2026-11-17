"""Waiting room: join, check position, receive a signed admission token when it is your turn."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .. import tokens
from ..ratelimit import enforce_rate_limit
from ..sales import require_sale

router = APIRouter(prefix="/queue", tags=["waiting-room"])


class JoinIn(BaseModel):
    buyer_id: str = Field(min_length=1, max_length=64)


async def _status(ctx, sale, buyer_id: str) -> dict:
    r, k = ctx.redis, sale.keys
    stock = int(await r.get(k.stock) or 0)
    sold_out = stock <= 0 and await r.zcard(k.reservations) == 0

    if await r.exists(k.admitted(buyer_id)):
        ttl = await r.ttl(k.admitted(buyer_id))
        token = tokens.issue(ctx.settings.hmac_secret, buyer_id, sale.id, max(ttl, 1))
        return {"status": "admitted", "token": token, "expires_in": ttl, "sold_out": sold_out}

    rank = await r.zrank(k.queue, buyer_id)
    if rank is None:
        return {"status": "not_in_queue", "sold_out": sold_out}
    position = rank + 1
    wait = position / max(ctx.settings.admission_rate_per_second, 0.001)
    return {
        "status": "waiting",
        "position": position,
        "queue_length": await r.zcard(k.queue),
        "estimated_wait_seconds": round(wait, 1),
        "sold_out": sold_out,
    }


@router.post("/join")
async def join(body: JoinIn, request: Request):
    ctx = request.app.state.ctx
    sale = await require_sale(ctx, "safe")
    await enforce_rate_limit(ctx, sale, body.buyer_id)
    k = sale.keys
    if not await ctx.redis.exists(k.admitted(body.buyer_id)):
        seq = await ctx.redis.incr(k.queue_seq)
        await ctx.redis.zadd(k.queue, {body.buyer_id: seq}, nx=True)  # joining twice keeps your spot
    return await _status(ctx, sale, body.buyer_id)


@router.get("/position")
async def position(buyer_id: str, request: Request):
    ctx = request.app.state.ctx
    sale = await require_sale(ctx, "safe")
    await enforce_rate_limit(ctx, sale, buyer_id)
    return await _status(ctx, sale, buyer_id)

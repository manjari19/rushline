"""Simulated rush for the dashboard: thousands of fake buyers calling the real routes.

Buyers talk to the app through an in-process HTTP client, so every request goes through the same
routing, rate limiting, Lua scripts and Postgres code a real browser would hit. (For honest
external load numbers use k6; this simulator shares the API's CPU.)
"""
import asyncio
import logging
import random

import httpx

from .context import Context
from .sales import Sale, get_active_sale

POLL_SECONDS = 1.5
log = logging.getLogger("rushline.rush")


def status_key(sale: Sale) -> str:
    return f"{sale.keys.prefix}rush"


async def read_status(ctx: Context, sale: Sale) -> dict:
    raw = await ctx.redis.hgetall(status_key(sale))
    total = int(raw.get("total", 0))
    finished = int(raw.get("finished", 0))
    return {
        "total": total,
        "finished": finished,
        "running": total > 0 and finished < total,
        "bought": int(raw.get("bought", 0)),
        "sold_out": int(raw.get("sold_out", 0)),
        "abandoned": int(raw.get("abandoned", 0)),
        "errors": int(raw.get("error", 0)),
    }


async def start(app, ctx: Context, sale: Sale, buyers: int, ramp_seconds: float, abandon_rate: float):
    """Launch the buyers in the background and return immediately."""
    await ctx.redis.delete(status_key(sale))
    await ctx.redis.hset(status_key(sale), mapping={"total": buyers, "finished": 0})
    asyncio.create_task(_run(app, ctx, sale, buyers, ramp_seconds, abandon_rate))


async def _run(app, ctx, sale, buyers, ramp_seconds, abandon_rate):
    limits = httpx.Limits(max_connections=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://rush", timeout=60, limits=limits
    ) as client:
        await asyncio.gather(
            *(_buyer(client, ctx, sale, i, ramp_seconds, abandon_rate) for i in range(buyers))
        )


class Cancelled(Exception):
    """The sale was reset or switched while this buyer was mid-journey."""


async def _check_active(ctx: Context, sale: Sale) -> None:
    current = await get_active_sale(ctx)
    if current is None or current.id != sale.id:
        raise Cancelled


async def _buyer(client, ctx, sale, index, ramp_seconds, abandon_rate):
    await asyncio.sleep(random.uniform(0, ramp_seconds))
    outcome = "sold_out"
    try:
        await _check_active(ctx, sale)
        buyer = f"rush-{sale.id}-{index}"
        if sale.mode == "naive":
            r = await client.post("/naive/checkout", json={"buyer_id": buyer})
            outcome = "bought" if r.status_code == 201 else "sold_out"
        else:
            outcome = await _safe_journey(client, ctx, sale, buyer, abandon_rate)
    except Cancelled:
        return  # the old sale's data is gone; don't write anything back
    except Exception as exc:
        log.warning("simulated buyer failed: %r", exc)
        outcome = "error"
    pipe = ctx.redis.pipeline()
    pipe.hincrby(status_key(sale), outcome, 1)
    pipe.hincrby(status_key(sale), "finished", 1)
    await pipe.execute()


async def _safe_journey(client, ctx, sale, buyer, abandon_rate) -> str:
    await client.post("/queue/join", json={"buyer_id": buyer})
    token = None
    while token is None:  # wait in the waiting room
        await asyncio.sleep(POLL_SECONDS * random.uniform(0.8, 1.2))
        await _check_active(ctx, sale)
        r = await client.get("/queue/position", params={"buyer_id": buyer})
        if r.status_code == 429:
            continue
        if r.status_code != 200:
            return "error"
        body = r.json()
        if body["status"] == "admitted":
            token = body["token"]
        elif body["sold_out"]:
            return "sold_out"

    await _check_active(ctx, sale)
    r = await client.post("/reserve", json={"buyer_id": buyer}, headers={"X-Admission-Token": token})
    if r.status_code == 409:
        return "sold_out"
    if r.status_code != 201:
        return "error"
    reservation_id = r.json()["reservation_id"]

    if random.random() < abandon_rate:  # walked away with the item in their cart
        return "abandoned"

    for _ in range(4):  # retry flaky payments a few times
        await _check_active(ctx, sale)
        r = await client.post("/pay", json={"reservation_id": reservation_id})
        if r.status_code == 200:
            break
    else:
        return "abandoned"
    r = await client.post(
        "/confirm", json={"reservation_id": reservation_id}, headers={"Idempotency-Key": f"{buyer}-confirm"}
    )
    return "bought" if r.status_code == 201 else "abandoned"

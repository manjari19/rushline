"""Safe mode checkout: reserve (atomic Redis) -> pay (fake) -> confirm (idempotent Postgres write)."""
import asyncio
import random
import time
import uuid

import asyncpg
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .. import events, tokens
from ..ratelimit import enforce_rate_limit
from ..sales import require_sale

router = APIRouter(tags=["checkout"])


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


class ReserveIn(BaseModel):
    buyer_id: str = Field(min_length=1, max_length=64)


class ReservationIn(BaseModel):
    reservation_id: str = Field(min_length=1, max_length=64)


@router.get("/sale")
async def current_sale(request: Request):
    """Public info for the buyer page: what is on sale and whether anything is left."""
    ctx = request.app.state.ctx
    sale = await require_sale(ctx)
    if sale.mode == "safe":
        left = int(await ctx.redis.get(sale.keys.stock) or 0)
    else:
        left = await ctx.pool.fetchval("SELECT stock_remaining FROM products WHERE id = $1", sale.id)
    return {"sale_id": sale.id, "name": sale.name, "price_cents": sale.price_cents,
            "mode": sale.mode, "stock_left": max(left, 0), "initial_stock": sale.initial_stock,
            "reservation_ttl_seconds": ctx.settings.reservation_ttl_seconds}


@router.post("/reserve", status_code=201)
async def reserve(body: ReserveIn, request: Request, x_admission_token: str | None = Header(None)):
    ctx = request.app.state.ctx
    sale = await require_sale(ctx, "safe")
    await enforce_rate_limit(ctx, sale, body.buyer_id)

    if not x_admission_token or not tokens.verify(
        ctx.settings.hmac_secret, x_admission_token, body.buyer_id, sale.id
    ):
        raise error(401, "not_admitted", "Join the waiting room first and wait to be admitted.")

    k, ttl = sale.keys, ctx.settings.reservation_ttl_seconds
    now = time.time()
    reservation_id = uuid.uuid4().hex
    status, rid = await ctx.scripts.reserve(
        keys=[k.stock, k.reservations, k.buyer_res(body.buyer_id), k.done, k.res(reservation_id)],
        args=[reservation_id, body.buyer_id, now + ttl, sale.price_cents, ttl + 60],
    )
    if status == 0:
        await events.record(ctx, sale, body.buyer_id, "rejected")
        raise error(409, "sold_out", "Sold out. Thanks for being here!")
    if status == 3:
        raise error(409, "already_purchased", "You already bought this item.")

    if status == 1:
        await events.record(ctx, sale, body.buyer_id, "reserved")
    expires_at = float(await ctx.redis.zscore(k.reservations, rid) or now + ttl)
    return {"reservation_id": rid, "expires_at": expires_at, "amount_cents": sale.price_cents,
            "resumed": status == 2}


@router.post("/pay")
async def pay(body: ReservationIn, request: Request):
    """Fake payment provider: random latency, small random failure rate."""
    ctx = request.app.state.ctx
    sale = await require_sale(ctx, "safe")
    await enforce_rate_limit(ctx, sale, body.reservation_id)
    k, s = sale.keys, ctx.settings

    expires_at = await ctx.redis.zscore(k.reservations, body.reservation_id)
    if expires_at is None or expires_at <= time.time():
        raise error(410, "reservation_expired", "Your reservation expired.")

    await asyncio.sleep(random.uniform(s.payment_min_ms, s.payment_max_ms) / 1000)
    if random.random() < s.payment_failure_rate:
        raise error(402, "payment_failed", "Payment failed. Your item is still held, try again.")

    marked = await ctx.scripts.mark_paid(
        keys=[k.reservations, k.res(body.reservation_id)], args=[body.reservation_id, time.time()]
    )
    if not marked:
        raise error(410, "reservation_expired", "Your reservation expired while paying.")
    return {"status": "paid"}


def order_json(row, replayed: bool) -> dict:
    return {"order_id": str(row["id"]), "buyer_id": row["buyer_id"],
            "amount_cents": row["amount_cents"], "replayed": replayed}


@router.post("/confirm", status_code=201)
async def confirm(
    body: ReservationIn, request: Request, idempotency_key: str | None = Header(None)
):
    ctx = request.app.state.ctx
    sale = await require_sale(ctx, "safe")
    if not idempotency_key:
        raise error(400, "idempotency_key_required", "Send an Idempotency-Key header.")
    await enforce_rate_limit(ctx, sale, body.reservation_id)
    k = sale.keys

    # 1. A retry of a finished request just replays the original answer.
    existing = await _order_by_key(ctx, sale, idempotency_key)
    if existing:
        return order_json(existing, replayed=True)

    # 2. Two copies of the same request at once: only one may proceed.
    if not await ctx.redis.set(k.idem(idempotency_key), "1", nx=True, ex=30):
        for _ in range(30):  # the other copy is mid-flight: wait briefly for its order
            existing = await _order_by_key(ctx, sale, idempotency_key)
            if existing:
                return order_json(existing, replayed=True)
            await asyncio.sleep(0.1)
        raise error(409, "in_progress", "This request is already being processed.")

    consumed = False
    try:
        buyer = await ctx.redis.hget(k.res(body.reservation_id), "buyer")
        if buyer is None:
            raise error(410, "reservation_expired", "Your reservation expired.")

        outcome = await ctx.scripts.consume(
            keys=[k.reservations, k.buyer_res(buyer), k.res(body.reservation_id), k.done],
            args=[body.reservation_id, buyer, time.time()],
        )
        if outcome == -2:
            raise error(402, "payment_required", "Pay before confirming.")
        if outcome != 1:
            raise error(410, "reservation_expired", "Your reservation expired.")
        consumed = True

        row = await _write_order(ctx, sale, buyer, body.reservation_id, idempotency_key)
        await events.record(ctx, sale, buyer, "confirmed")
        return order_json(row, replayed=False)
    except BaseException:
        # Anything went wrong after we consumed the reservation: give the unit back.
        if consumed:
            await _undo_consume(ctx, sale, buyer)
        await ctx.redis.delete(k.idem(idempotency_key))
        raise


async def _order_by_key(ctx, sale, key: str):
    return await ctx.pool.fetchrow(
        "SELECT * FROM orders WHERE product_id = $1 AND idempotency_key = $2", sale.id, key
    )


async def _write_order(ctx, sale, buyer: str, reservation_id: str, key: str):
    """One Postgres transaction: take one unit of stock AND insert the order, or neither."""
    try:
        async with ctx.pool.acquire() as conn, conn.transaction():
            left = await conn.fetchval(
                "UPDATE products SET stock_remaining = stock_remaining - 1 "
                "WHERE id = $1 AND stock_remaining > 0 RETURNING stock_remaining",
                sale.id,
            )
            if left is None:  # safety net: Redis said yes but Postgres is out of stock
                raise error(409, "sold_out", "Sold out.")
            return await conn.fetchrow(
                "INSERT INTO orders (id, product_id, buyer_id, amount_cents, idempotency_key, reservation_id) "
                "VALUES ($1, $2, $3, $4, $5, $6) RETURNING *",
                uuid.uuid4(), sale.id, buyer, sale.price_cents, key, reservation_id,
            )
    except asyncpg.UniqueViolationError:
        # Backstop: this key, reservation or buyer already has an order. The caller returns the unit.
        raise error(409, "already_purchased", "An order already exists for this request.")


async def _undo_consume(ctx, sale, buyer: str) -> None:
    pipe = ctx.redis.pipeline(transaction=True)
    pipe.incr(sale.keys.stock)
    pipe.srem(sale.keys.done, buyer)
    await pipe.execute()

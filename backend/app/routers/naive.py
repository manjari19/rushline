"""Naive mode: read stock, then write stock. No locking, no transaction. Kept to show it oversells."""
import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import events
from ..sales import require_sale

router = APIRouter(prefix="/naive", tags=["naive"])


class CheckoutIn(BaseModel):
    buyer_id: str = Field(min_length=1, max_length=64)


@router.post("/checkout", status_code=201)
async def naive_checkout(body: CheckoutIn, request: Request):
    ctx = request.app.state.ctx
    sale = await require_sale(ctx, "naive")

    # BUG ON PURPOSE: two buyers can both read "1 left" before either writes "0 left".
    stock = await ctx.pool.fetchval("SELECT stock_remaining FROM products WHERE id = $1", sale.id)
    if stock <= 0:
        await events.record(ctx, sale, body.buyer_id, "rejected")
        raise HTTPException(409, {"code": "sold_out", "message": "Sold out."})

    if ctx.settings.naive_think_ms:
        await asyncio.sleep(ctx.settings.naive_think_ms / 1000)

    await ctx.pool.execute("UPDATE products SET stock_remaining = $2 WHERE id = $1", sale.id, stock - 1)
    order_id = uuid.uuid4()
    await ctx.pool.execute(
        "INSERT INTO orders (id, product_id, buyer_id, amount_cents) VALUES ($1, $2, $3, $4)",
        order_id, sale.id, body.buyer_id, sale.price_cents,
    )
    await events.record(ctx, sale, body.buyer_id, "confirmed")
    return {"order_id": str(order_id)}

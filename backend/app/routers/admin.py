"""Admin: create or reset a sale, read live stats."""
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..sales import create_sale, require_sale

router = APIRouter(prefix="/admin", tags=["admin"])


class SaleIn(BaseModel):
    name: str = Field("Rushline Founders Hoodie", max_length=100)
    price_cents: int = Field(4900, ge=0)
    stock: int = Field(100, ge=1, le=1_000_000)
    mode: Literal["naive", "safe"] = "safe"


@router.post("/sale", status_code=201)
async def create_or_reset_sale(body: SaleIn, request: Request):
    """Creating a sale also resets everything: a new product row and clean Redis state."""
    sale = await create_sale(request.app.state.ctx, body.name, body.price_cents, body.stock, body.mode)
    return {"sale_id": sale.id, "mode": sale.mode, "stock": sale.initial_stock}


async def collect_stats(request: Request) -> dict:
    ctx = request.app.state.ctx
    sale = await require_sale(ctx)
    k = sale.keys

    confirmed = await ctx.pool.fetchval("SELECT count(*) FROM orders WHERE product_id = $1", sale.id)
    if sale.mode == "safe":
        stock_left = int(await ctx.redis.get(k.stock) or 0)
    else:
        stock_left = await ctx.pool.fetchval(
            "SELECT stock_remaining FROM products WHERE id = $1", sale.id
        )

    series = await request.app.state.metrics.series(60)
    return {
        "sale_id": sale.id,
        "name": sale.name,
        "mode": sale.mode,
        "initial_stock": sale.initial_stock,
        "stock_left": stock_left,
        "queue_length": await ctx.redis.zcard(k.queue),
        "active_reservations": await ctx.redis.zcard(k.reservations),
        "confirmed_orders": confirmed,
        "oversold_units": max(0, confirmed - sale.initial_stock),
        "rps": series[-1]["rps"],
        "avg_latency_ms": series[-1]["avg_ms"],
        "series": series,
    }


@router.get("/stats")
async def stats(request: Request):
    return await collect_stats(request)

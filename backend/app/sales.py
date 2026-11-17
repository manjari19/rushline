"""The 'active sale': which product is on sale, in which mode. Cached in Redis, backed by Postgres."""
import json
from dataclasses import asdict, dataclass

from fastapi import HTTPException

from .context import Context
from .keys import ACTIVE_SALE, Keys


@dataclass
class Sale:
    id: int
    name: str
    price_cents: int
    initial_stock: int
    mode: str  # "naive" | "safe"

    @property
    def keys(self) -> Keys:
        return Keys(self.id)


async def create_sale(ctx: Context, name: str, price_cents: int, stock: int, mode: str) -> Sale:
    """Start a fresh sale. Old sale data is wiped from Redis; Postgres keeps the history."""
    previous = await get_active_sale(ctx)
    row = await ctx.pool.fetchrow(
        """INSERT INTO products (name, price_cents, initial_stock, stock_remaining, mode)
           VALUES ($1, $2, $3, $3, $4) RETURNING id""",
        name, price_cents, stock, mode,
    )
    sale = Sale(row["id"], name, price_cents, stock, mode)
    if previous:
        await _delete_sale_keys(ctx, previous)
    await ctx.redis.set(sale.keys.stock, stock)
    await ctx.redis.set(ACTIVE_SALE, json.dumps(asdict(sale)))
    return sale


async def get_active_sale(ctx: Context) -> Sale | None:
    cached = await ctx.redis.get(ACTIVE_SALE)
    if cached:
        return Sale(**json.loads(cached))
    # Redis was wiped: fall back to the newest product. Safe-mode stock is rebuilt from Postgres.
    row = await ctx.pool.fetchrow("SELECT * FROM products ORDER BY id DESC LIMIT 1")
    if row is None:
        return None
    sale = Sale(row["id"], row["name"], row["price_cents"], row["initial_stock"], row["mode"])
    await ctx.redis.set(sale.keys.stock, row["stock_remaining"], nx=True)
    await ctx.redis.set(ACTIVE_SALE, json.dumps(asdict(sale)))
    return sale


async def _delete_sale_keys(ctx: Context, sale: Sale) -> None:
    async for key in ctx.redis.scan_iter(match=f"{sale.keys.prefix}*", count=1000):
        await ctx.redis.delete(key)


async def require_sale(ctx: Context, mode: str | None = None) -> Sale:
    """The active sale, or a clear HTTP error if there is none or it runs in the other mode."""
    sale = await get_active_sale(ctx)
    if sale is None:
        raise HTTPException(404, {"code": "no_sale", "message": "No sale is running yet."})
    if mode and sale.mode != mode:
        raise HTTPException(
            409, {"code": "wrong_mode", "message": f"The active sale is in {sale.mode} mode."}
        )
    return sale

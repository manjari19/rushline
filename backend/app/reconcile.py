"""Reconciliation: confirmed orders in Postgres must never exceed the starting stock.

Run:  docker compose exec api python -m app.reconcile          (latest sale)
      docker compose exec api python -m app.reconcile --all    (every sale ever run)
Exit code 0 = all good, 1 = a problem was found.
"""
import asyncio
import sys

from .config import get_settings
from .context import Context


async def reconcile(ctx: Context, all_sales: bool = False) -> list[dict]:
    query = """
        SELECT p.id, p.name, p.mode, p.initial_stock, p.stock_remaining, count(o.id) AS orders
        FROM products p LEFT JOIN orders o ON o.product_id = p.id
        GROUP BY p.id ORDER BY p.id DESC
    """ + ("" if all_sales else " LIMIT 1")
    results = []
    for row in await ctx.pool.fetch(query):
        orders, initial = row["orders"], row["initial_stock"]
        problems = []
        if orders > initial:
            problems.append(f"OVERSOLD: {orders} orders for {initial} units ({orders - initial} too many)")
        if row["mode"] == "safe" and row["stock_remaining"] != initial - orders:
            problems.append(
                f"stock_remaining={row['stock_remaining']} but initial - orders = {initial - orders}"
            )
        results.append({"sale_id": row["id"], "name": row["name"], "mode": row["mode"],
                        "initial_stock": initial, "orders": orders, "problems": problems})
    return results


async def main() -> int:
    ctx = Context(get_settings())
    await ctx.connect()
    try:
        results = await reconcile(ctx, all_sales="--all" in sys.argv)
    finally:
        await ctx.close()
    failed = False
    for r in results:
        status = "OK  " if not r["problems"] else "FAIL"
        print(f"[{status}] sale {r['sale_id']} ({r['mode']}): {r['orders']} orders / {r['initial_stock']} units")
        for problem in r["problems"]:
            print(f"        - {problem}")
        failed |= bool(r["problems"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

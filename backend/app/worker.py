"""Background worker: admits buyers from the waiting room and returns expired reservations to stock."""
import asyncio
import logging
import time

from .config import get_settings
from .context import Context
from .sales import get_active_sale

log = logging.getLogger("rushline.worker")
TICK_SECONDS = 0.2
EXPIRY_BATCH = 500


async def admit(ctx: Context, count: int) -> int:
    """Let the next `count` buyers in. Returns how many were admitted."""
    sale = await get_active_sale(ctx)
    if sale is None or sale.mode != "safe" or count <= 0:
        return 0
    s = ctx.settings
    return await ctx.scripts.admit(
        keys=[sale.keys.queue],
        args=[count, sale.keys.prefix + "admitted:", s.admission_ttl_seconds],
    )


async def release_expired(ctx: Context) -> int:
    """Return stock held by expired reservations. Returns how many were released."""
    sale = await get_active_sale(ctx)
    if sale is None or sale.mode != "safe":
        return 0
    k = sale.keys
    return await ctx.scripts.expire(
        keys=[k.reservations, k.stock], args=[time.time(), EXPIRY_BATCH, k.prefix]
    )


async def run() -> None:
    ctx = Context(get_settings())
    await ctx.connect()
    log.info("worker started: admitting %s buyers/sec", ctx.settings.admission_rate_per_second)
    budget = 0.0  # fractional admissions carry over between ticks
    try:
        while True:
            budget += ctx.settings.admission_rate_per_second * TICK_SECONDS
            whole = int(budget)
            budget -= whole
            try:
                await admit(ctx, whole)
                released = await release_expired(ctx)
                if released:
                    log.info("released %d expired reservations", released)
            except Exception:
                log.exception("worker tick failed")
            await asyncio.sleep(TICK_SECONDS)
    finally:
        await ctx.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())

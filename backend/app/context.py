"""Shared connections (Postgres pool, Redis client, Lua scripts) used by the API and the worker."""
import asyncio
from pathlib import Path

import asyncpg
from redis.asyncio import Redis

from .config import Settings

LUA_DIR = Path(__file__).parent / "lua"
SCHEMA = Path(__file__).parent / "schema.sql"


class Scripts:
    """Each Lua file is registered once; Redis runs it atomically."""

    def __init__(self, redis: Redis):
        load = lambda name: redis.register_script((LUA_DIR / f"{name}.lua").read_text())
        self.reserve = load("reserve")
        self.expire = load("expire")
        self.consume = load("consume")
        self.mark_paid = load("mark_paid")
        self.admit = load("admit")
        self.rate_limit = load("rate_limit")


class Context:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pool: asyncpg.Pool
        self.redis: Redis
        self.scripts: Scripts

    async def connect(self) -> None:
        self.pool = await self._create_pool()
        self.redis = Redis.from_url(self.settings.redis_url, decode_responses=True)
        self.scripts = Scripts(self.redis)
        async with self.pool.acquire() as conn:
            # The advisory lock stops API workers from racing to create tables at startup.
            await conn.execute("SELECT pg_advisory_lock(7001)")
            try:
                await conn.execute(SCHEMA.read_text())
            finally:
                await conn.execute("SELECT pg_advisory_unlock(7001)")

    async def _create_pool(self) -> asyncpg.Pool:
        for attempt in range(30):  # Postgres may still be starting
            try:
                return await asyncpg.create_pool(
                    self.settings.database_url, min_size=2, max_size=self.settings.db_pool_size
                )
            except (OSError, asyncpg.CannotConnectNowError):
                await asyncio.sleep(1)
        raise RuntimeError("Postgres is not reachable")

    async def close(self) -> None:
        await self.pool.close()
        await self.redis.aclose()

from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx
import pytest
import pytest_asyncio

from app.config import get_settings
from app.main import app


async def use_separate_test_database() -> None:
    """Tests get their own Postgres database so they never touch data from a live demo."""
    settings = get_settings()
    parts = urlsplit(settings.database_url)
    admin_dsn = urlunsplit(parts._replace(path="/postgres"))
    conn = await asyncpg.connect(admin_dsn)
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'rushline_test'"):
            await conn.execute("CREATE DATABASE rushline_test")
    finally:
        await conn.close()
    settings.database_url = urlunsplit(parts._replace(path="/rushline_test"))


@pytest_asyncio.fixture(scope="session")
async def ctx():
    """Starts the real app (Postgres pool, Redis, Lua scripts) once for the whole test run."""
    await use_separate_test_database()
    async with app.router.lifespan_context(app):
        await app.state.ctx.redis.flushdb()  # tests use their own Redis db (see docker-compose)
        yield app.state.ctx


@pytest_asyncio.fixture(scope="session")
async def client(ctx):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
        yield c


@pytest.fixture(autouse=True)
def test_settings():
    """Deterministic, fast settings for every test; restored afterwards."""
    settings = get_settings()
    saved = settings.model_copy()
    settings.payment_failure_rate = 0.0
    settings.payment_min_ms = 0
    settings.payment_max_ms = 5
    settings.rate_limit_max = 100_000
    settings.naive_think_ms = 0
    settings.reservation_ttl_seconds = 120
    yield settings
    for field in type(settings).model_fields:
        setattr(settings, field, getattr(saved, field))


async def start_sale(client, stock: int, mode: str = "safe") -> int:
    r = await client.post("/admin/sale", json={"stock": stock, "mode": mode, "price_cents": 1000})
    assert r.status_code == 201
    return r.json()["sale_id"]


async def stats(client) -> dict:
    return (await client.get("/admin/stats")).json()

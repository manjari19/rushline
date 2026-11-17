"""Requests-per-second and latency, recorded in memory and flushed to Redis once a second.

Recording in memory keeps the hot path free of extra Redis round trips.
"""
import asyncio
import time
from collections import defaultdict

from redis.asyncio import Redis

SKIP_PREFIXES = ("/admin", "/health", "/docs", "/openapi")
LAG_SECONDS = 2  # read only seconds old enough that every process has flushed them


class Metrics:
    def __init__(self, redis: Redis):
        self.redis = redis
        self._buckets: dict[int, list[float]] = defaultdict(lambda: [0, 0.0])  # sec -> [count, ms_sum]
        self._task: asyncio.Task | None = None

    def record(self, latency_ms: float) -> None:
        bucket = self._buckets[int(time.time())]
        bucket[0] += 1
        bucket[1] += latency_ms

    async def flush(self, include_current: bool = False) -> None:
        now = int(time.time())
        done = [s for s in self._buckets if include_current or s < now]
        if not done:
            return
        pipe = self.redis.pipeline()
        for sec in done:
            count, total = self._buckets.pop(sec)
            pipe.hincrby(f"metrics:{sec}", "count", int(count))
            pipe.hincrbyfloat(f"metrics:{sec}", "ms_sum", total)
            pipe.expire(f"metrics:{sec}", 300)
        await pipe.execute()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            try:
                await self.flush()
            except Exception:  # metrics must never take the API down
                pass

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        await self.flush(include_current=True)

    async def series(self, seconds: int = 60) -> list[dict]:
        """Last `seconds` completed seconds: [{t, rps, avg_ms}]."""
        end = int(time.time()) - LAG_SECONDS
        secs = list(range(end - seconds + 1, end + 1))
        pipe = self.redis.pipeline()
        for sec in secs:
            pipe.hgetall(f"metrics:{sec}")
        rows = await pipe.execute()
        out = []
        for sec, row in zip(secs, rows):
            count = int(row.get("count", 0))
            total = float(row.get("ms_sum", 0))
            out.append({"t": sec, "rps": count, "avg_ms": round(total / count, 2) if count else 0})
        return out


class MetricsMiddleware:
    """Pure ASGI middleware (much cheaper than BaseHTTPMiddleware under load)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith(SKIP_PREFIXES):
            return await self.app(scope, receive, send)
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send)
        finally:
            scope["app"].state.metrics.record((time.perf_counter() - start) * 1000)

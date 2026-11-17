from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .context import Context
from .metrics import Metrics, MetricsMiddleware
from .routers import admin, checkout, naive, queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx = Context(get_settings())
    await ctx.connect()
    app.state.ctx = ctx
    app.state.metrics = Metrics(ctx.redis)
    app.state.metrics.start()
    yield
    await app.state.metrics.stop()
    await ctx.close()


app = FastAPI(title="Rushline", description="Flash-sale checkout engine", lifespan=lifespan)
app.add_middleware(MetricsMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(admin.router)
app.include_router(naive.router)
app.include_router(queue.router)
app.include_router(checkout.router)


@app.get("/health")
async def health():
    return {"ok": True}

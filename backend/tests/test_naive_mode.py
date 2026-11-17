"""Naive mode exists to be wrong. This test documents that it really does oversell."""
import asyncio

from app.reconcile import reconcile

from .conftest import start_sale, stats


async def test_naive_mode_oversells(client, ctx, test_settings):
    test_settings.naive_think_ms = 20  # widen the read-then-write race so the test is reliable
    stock, buyers = 50, 200
    await start_sale(client, stock, mode="naive")

    responses = await asyncio.gather(
        *(client.post("/naive/checkout", json={"buyer_id": f"b{i}"}) for i in range(buyers))
    )
    sold = sum(r.status_code == 201 for r in responses)

    s = await stats(client)
    assert sold > stock, "naive checkout was expected to oversell"
    assert s["confirmed_orders"] == sold
    assert s["oversold_units"] == sold - stock > 0

    (result,) = await reconcile(ctx)
    assert any("OVERSOLD" in p for p in result["problems"])


async def test_naive_mode_works_without_concurrency(client, ctx):
    """With one buyer at a time the naive code is correct, which is why the bug hides until a rush."""
    await start_sale(client, 3, mode="naive")
    codes = [(await client.post("/naive/checkout", json={"buyer_id": f"b{i}"})).status_code
             for i in range(5)]
    assert codes == [201, 201, 201, 409, 409]
    assert (await stats(client))["oversold_units"] == 0


async def test_naive_mode_feeds_activity(client, ctx):
    await start_sale(client, 1, mode="naive")
    await client.post("/naive/checkout", json={"buyer_id": "a"})
    await client.post("/naive/checkout", json={"buyer_id": "b"})
    feed = (await client.get("/admin/events")).json()["events"]
    assert [(e["buyer_id"], e["event"]) for e in feed] == [("b", "rejected"), ("a", "confirmed")]

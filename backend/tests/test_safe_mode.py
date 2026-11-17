"""Safe mode: the waiting room, atomic reservations, payments, idempotent confirms, and no overselling."""
import asyncio
import time

from app.reconcile import reconcile
from app.worker import admit, release_expired

from .conftest import start_sale, stats


async def join_and_admit(client, ctx, buyer: str) -> str:
    await client.post("/queue/join", json={"buyer_id": buyer})
    await admit(ctx, 1)
    r = await client.get("/queue/position", params={"buyer_id": buyer})
    assert r.json()["status"] == "admitted"
    return r.json()["token"]


async def reserve(client, buyer: str, token: str):
    return await client.post("/reserve", json={"buyer_id": buyer}, headers={"X-Admission-Token": token})


async def pay_until_ok(client, reservation_id: str) -> bool:
    for _ in range(15):
        r = await client.post("/pay", json={"reservation_id": reservation_id})
        if r.status_code == 200:
            return True
        if r.status_code != 402:
            return False
    return False


async def confirm(client, reservation_id: str, key: str):
    return await client.post(
        "/confirm", json={"reservation_id": reservation_id}, headers={"Idempotency-Key": key}
    )


# ---------------------------------------------------------------- the headline guarantee

async def test_no_oversell_under_concurrent_rush(client, ctx, test_settings):
    """200 buyers race for 25 units (with flaky payments). Exactly 25 orders, never 26."""
    test_settings.payment_failure_rate = 0.2
    stock, buyers = 25, 200
    await start_sale(client, stock)
    ids = [f"buyer-{i}" for i in range(buyers)]

    await asyncio.gather(*(client.post("/queue/join", json={"buyer_id": b}) for b in ids))
    assert await admit(ctx, buyers) == buyers

    async def buyer_journey(buyer: str) -> str:
        token = (await client.get("/queue/position", params={"buyer_id": buyer})).json()["token"]
        r = await reserve(client, buyer, token)
        if r.status_code == 409:
            return "sold_out"
        assert r.status_code == 201, r.text
        rid = r.json()["reservation_id"]
        assert await pay_until_ok(client, rid)
        r = await confirm(client, rid, f"key-{buyer}")
        assert r.status_code == 201, r.text
        return "bought"

    outcomes = await asyncio.gather(*(buyer_journey(b) for b in ids))

    assert outcomes.count("bought") == stock
    assert outcomes.count("sold_out") == buyers - stock
    s = await stats(client)
    assert s["confirmed_orders"] == stock
    assert s["oversold_units"] == 0
    assert s["stock_left"] == 0
    assert s["active_reservations"] == 0
    (result,) = await reconcile(ctx)
    assert result["problems"] == []


async def test_atomic_reserve_never_exceeds_stock(client, ctx):
    """500 buyers hit /reserve at the same instant for 10 units: exactly 10 win."""
    await start_sale(client, 10)
    ids = [f"b{i}" for i in range(500)]
    await asyncio.gather(*(client.post("/queue/join", json={"buyer_id": b}) for b in ids))
    await admit(ctx, 500)
    tokens = {
        b: (await client.get("/queue/position", params={"buyer_id": b})).json()["token"] for b in ids
    }
    responses = await asyncio.gather(*(reserve(client, b, tokens[b]) for b in ids))
    codes = [r.status_code for r in responses]
    assert codes.count(201) == 10
    assert codes.count(409) == 490
    assert (await stats(client))["active_reservations"] == 10


# ---------------------------------------------------------------- idempotency

async def test_confirm_retries_never_double_order(client, ctx):
    await start_sale(client, 5)
    token = await join_and_admit(client, ctx, "alice")
    rid = (await reserve(client, "alice", token)).json()["reservation_id"]
    assert await pay_until_ok(client, rid)

    # Ten identical requests at once (a nervous double-clicker with a flaky network).
    responses = await asyncio.gather(*(confirm(client, rid, "same-key") for _ in range(10)))
    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["order_id"] for r in responses}) == 1

    # A later retry replays the same order.
    again = await confirm(client, rid, "same-key")
    assert again.status_code == 201 and again.json()["replayed"] is True
    assert (await stats(client))["confirmed_orders"] == 1


async def test_confirm_requires_idempotency_key(client, ctx):
    await start_sale(client, 5)
    token = await join_and_admit(client, ctx, "alice")
    rid = (await reserve(client, "alice", token)).json()["reservation_id"]
    r = await client.post("/confirm", json={"reservation_id": rid})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "idempotency_key_required"


async def test_buyer_cannot_buy_twice(client, ctx):
    await start_sale(client, 5)
    token = await join_and_admit(client, ctx, "alice")
    rid = (await reserve(client, "alice", token)).json()["reservation_id"]
    await pay_until_ok(client, rid)
    assert (await confirm(client, rid, "k1")).status_code == 201
    r = await reserve(client, "alice", token)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_purchased"


# ---------------------------------------------------------------- reservations and the worker

async def test_expired_reservation_returns_stock(client, ctx, test_settings):
    test_settings.reservation_ttl_seconds = 1
    await start_sale(client, 1)
    token = await join_and_admit(client, ctx, "alice")
    rid = (await reserve(client, "alice", token)).json()["reservation_id"]
    assert (await stats(client))["stock_left"] == 0

    await asyncio.sleep(1.2)
    assert await release_expired(ctx) == 1  # what the worker does every 200ms
    s = await stats(client)
    assert s["stock_left"] == 1 and s["active_reservations"] == 0

    # Paying/confirming the expired reservation is refused.
    assert (await client.post("/pay", json={"reservation_id": rid})).status_code == 410
    assert (await confirm(client, rid, "late")).status_code == 410

    # The freed unit can be bought by someone else.
    token2 = await join_and_admit(client, ctx, "bob")
    assert (await reserve(client, "bob", token2)).status_code == 201


async def test_reserve_is_resumable(client, ctx):
    """Refreshing the page must not burn a second unit."""
    await start_sale(client, 3)
    token = await join_and_admit(client, ctx, "alice")
    first = (await reserve(client, "alice", token)).json()
    second = (await reserve(client, "alice", token)).json()
    assert first["reservation_id"] == second["reservation_id"] and second["resumed"] is True
    assert (await stats(client))["stock_left"] == 2


async def test_payment_failure_keeps_reservation(client, ctx, test_settings):
    await start_sale(client, 2)
    token = await join_and_admit(client, ctx, "alice")
    rid = (await reserve(client, "alice", token)).json()["reservation_id"]

    test_settings.payment_failure_rate = 1.0
    r = await client.post("/pay", json={"reservation_id": rid})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "payment_failed"
    assert (await confirm(client, rid, "too-early")).status_code == 402  # unpaid cannot be confirmed
    assert (await stats(client))["active_reservations"] == 1

    test_settings.payment_failure_rate = 0.0
    assert (await client.post("/pay", json={"reservation_id": rid})).status_code == 200
    assert (await confirm(client, rid, "now-ok")).status_code == 201


# ---------------------------------------------------------------- waiting room

async def test_waiting_room_is_fifo_and_issues_tokens(client, ctx):
    await start_sale(client, 10)
    for b in ["a", "b", "c", "d"]:
        await client.post("/queue/join", json={"buyer_id": b})
    pos = (await client.get("/queue/position", params={"buyer_id": "c"})).json()
    assert pos["status"] == "waiting" and pos["position"] == 3 and pos["queue_length"] == 4

    assert await admit(ctx, 2) == 2  # a and b get in
    assert (await client.get("/queue/position", params={"buyer_id": "a"})).json()["status"] == "admitted"
    assert (await client.get("/queue/position", params={"buyer_id": "b"})).json()["status"] == "admitted"
    pos = (await client.get("/queue/position", params={"buyer_id": "c"})).json()
    assert pos["status"] == "waiting" and pos["position"] == 1

    # Joining twice does not lose your place.
    await client.post("/queue/join", json={"buyer_id": "c"})
    assert (await client.get("/queue/position", params={"buyer_id": "c"})).json()["position"] == 1


async def test_reserve_rejects_missing_wrong_and_tampered_tokens(client, ctx):
    await start_sale(client, 10)
    token = await join_and_admit(client, ctx, "alice")

    assert (await client.post("/reserve", json={"buyer_id": "alice"})).status_code == 401
    assert (await reserve(client, "mallory", token)).status_code == 401  # alice's token, mallory's id
    body, sig = token.split(".")
    assert (await reserve(client, "alice", f"{body}.{'0' * len(sig)}")).status_code == 401
    assert (await reserve(client, "alice", token)).status_code == 201


async def test_cannot_reserve_without_being_admitted(client, ctx):
    await start_sale(client, 10)
    await client.post("/queue/join", json={"buyer_id": "alice"})
    status = (await client.get("/queue/position", params={"buyer_id": "alice"})).json()
    assert status["status"] == "waiting" and "token" not in status


# ---------------------------------------------------------------- rate limiting

async def test_sliding_window_rate_limit(client, ctx, test_settings):
    test_settings.rate_limit_max = 5
    test_settings.rate_limit_window_seconds = 1
    await start_sale(client, 10)

    codes = [(await client.get("/queue/position", params={"buyer_id": "spammer"})).status_code
             for _ in range(7)]
    assert codes == [200] * 5 + [429] * 2
    limited = await client.get("/queue/position", params={"buyer_id": "spammer"})
    assert int(limited.headers["Retry-After"]) >= 1
    # Other buyers are unaffected.
    assert (await client.get("/queue/position", params={"buyer_id": "polite"})).status_code == 200

    await asyncio.sleep(1.1)  # the window slides past the old requests
    assert (await client.get("/queue/position", params={"buyer_id": "spammer"})).status_code == 200


# ---------------------------------------------------------------- admin

async def test_reset_wipes_state(client, ctx):
    await start_sale(client, 3)
    await client.post("/queue/join", json={"buyer_id": "alice"})
    await start_sale(client, 7)
    s = await stats(client)
    assert s["stock_left"] == 7 and s["queue_length"] == 0 and s["confirmed_orders"] == 0


async def test_wrong_mode_is_rejected(client, ctx):
    await start_sale(client, 3, mode="safe")
    r = await client.post("/naive/checkout", json={"buyer_id": "x"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "wrong_mode"


async def test_simulated_rush_never_oversells(client, ctx, test_settings):
    """The dashboard's rush button: 300 simulated buyers, 20 units, with abandoned carts."""
    test_settings.reservation_ttl_seconds = 2
    test_settings.admission_rate_per_second = 1000
    await start_sale(client, 20)
    r = await client.post("/admin/rush", json={"buyers": 300, "ramp_seconds": 1, "abandon_rate": 0.2})
    assert r.status_code == 202

    deadline = time.time() + 30
    while time.time() < deadline:
        await admit(ctx, 100)
        await release_expired(ctx)
        s = await stats(client)
        if not s["rush"]["running"]:
            break
        await asyncio.sleep(0.2)
    assert not s["rush"]["running"]
    assert s["confirmed_orders"] <= 20 and s["oversold_units"] == 0
    assert s["rush"]["bought"] == s["confirmed_orders"]


async def test_reset_mid_rush_cancels_old_buyers(client, ctx, test_settings):
    """Resetting the sale during a rush must not let the old rush's buyers leak into the new sale."""
    test_settings.admission_rate_per_second = 1000
    await start_sale(client, 20)
    await client.post("/admin/rush", json={"buyers": 300, "ramp_seconds": 2, "abandon_rate": 0})
    await asyncio.sleep(0.3)
    await start_sale(client, 20)  # the user clicks "Reset sale" mid-rush

    for _ in range(25):  # 5 seconds of worker activity
        await admit(ctx, 100)
        await asyncio.sleep(0.2)
    s = await stats(client)
    assert s["queue_length"] == 0 and s["active_reservations"] == 0
    assert s["confirmed_orders"] == 0 and s["stock_left"] == 20


# ---------------------------------------------------------------- live activity feed

async def events_of(client, limit=15):
    return (await client.get("/admin/events", params={"limit": limit})).json()["events"]


async def test_activity_feed_tracks_the_buyer_journey(client, ctx, test_settings):
    test_settings.reservation_ttl_seconds = 1
    await start_sale(client, 1)
    token = await join_and_admit(client, ctx, "alice")
    rid = (await reserve(client, "alice", token)).json()["reservation_id"]
    await pay_until_ok(client, rid)
    await confirm(client, rid, "k-alice")
    token_b = await join_and_admit(client, ctx, "bob")
    assert (await reserve(client, "bob", token_b)).status_code == 409  # sold out

    feed = await events_of(client)
    assert [(e["buyer_id"], e["event"]) for e in feed] == [
        ("bob", "rejected"), ("bob", "waiting"),
        ("alice", "confirmed"), ("alice", "reserved"), ("alice", "waiting"),
    ]  # newest first
    assert all(e["units"] == 1 and e["ts"] > 0 for e in feed)

    # Expiry shows up too.
    await start_sale(client, 1)
    token = await join_and_admit(client, ctx, "carol")
    await reserve(client, "carol", token)
    await asyncio.sleep(1.2)
    await release_expired(ctx)
    latest = (await events_of(client, 1))[0]
    assert (latest["buyer_id"], latest["event"]) == ("carol", "expired")


async def test_activity_feed_is_capped_and_limit_respected(client, ctx):
    await start_sale(client, 5)
    for i in range(70):
        await client.post("/queue/join", json={"buyer_id": f"b{i}"})
    assert len(await events_of(client, 15)) == 15
    assert len(await events_of(client, 500)) == 50  # capped at MAX_EVENTS
    assert (await events_of(client, 1))[0]["buyer_id"] == "b69"


async def test_activity_feed_can_be_disabled(client, ctx, test_settings):
    test_settings.activity_log = False
    await start_sale(client, 5)
    await client.post("/queue/join", json={"buyer_id": "quiet"})
    assert await events_of(client) == []


async def test_sold_out_events_collapse_into_one_entry(client, ctx):
    await start_sale(client, 1)
    tokens = {b: await join_and_admit(client, ctx, b) for b in ["a", "b", "c", "d", "e"]}
    for buyer, token in tokens.items():
        await reserve(client, buyer, token)  # "a" reserves, b to e are sold out
    feed = await events_of(client)
    sold_out = [e for e in feed if e["event"] == "rejected"]
    assert len(sold_out) == 1 and sold_out[0]["units"] == 4 and sold_out[0]["buyer_id"] == "e"

    # A different event in between starts a new run.
    await join_and_admit(client, ctx, "f")
    token = await join_and_admit(client, ctx, "g")
    await reserve(client, "g", token)
    feed = await events_of(client)
    assert [(e["event"], e["units"]) for e in feed[:4]] == [
        ("rejected", 1), ("waiting", 1), ("waiting", 1), ("rejected", 4),
    ]

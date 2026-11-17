"""Redis key names. Everything for one sale lives under 'sale:<id>:' so a reset is a clean slate."""

ACTIVE_SALE = "active_sale"


class Keys:
    def __init__(self, sale_id: int):
        self.prefix = f"sale:{sale_id}:"

    @property
    def stock(self) -> str:
        return self.prefix + "stock"

    @property
    def queue(self) -> str:          # ZSET: buyer_id scored by join order
        return self.prefix + "queue"

    @property
    def queue_seq(self) -> str:
        return self.prefix + "queue_seq"

    @property
    def reservations(self) -> str:   # ZSET: reservation_id scored by expiry time
        return self.prefix + "reservations"

    @property
    def done(self) -> str:           # SET: buyers who already bought
        return self.prefix + "done"

    def admitted(self, buyer: str) -> str:
        return f"{self.prefix}admitted:{buyer}"

    def buyer_res(self, buyer: str) -> str:
        return f"{self.prefix}buyer_res:{buyer}"

    def res(self, reservation_id: str) -> str:   # HASH: buyer, amount, paid
        return f"{self.prefix}res:{reservation_id}"

    def rate(self, identity: str) -> str:
        return f"{self.prefix}rl:{identity}"

    def idem(self, key: str) -> str:
        return f"{self.prefix}idem:{key}"

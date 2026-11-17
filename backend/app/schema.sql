CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    name            TEXT        NOT NULL,
    price_cents     INTEGER     NOT NULL,
    initial_stock   INTEGER     NOT NULL,
    stock_remaining INTEGER     NOT NULL CHECK (stock_remaining >= 0),
    mode            TEXT        NOT NULL CHECK (mode IN ('naive', 'safe')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    id              UUID PRIMARY KEY,
    product_id      INTEGER     NOT NULL REFERENCES products(id),
    buyer_id        TEXT        NOT NULL,
    amount_cents    INTEGER     NOT NULL,
    idempotency_key TEXT,             -- safe mode only: a retry can never create a second order
    reservation_id  TEXT UNIQUE,      -- safe mode only: one reservation becomes at most one order
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS orders_product_idx ON orders (product_id);

-- Idempotency keys are unique within a sale (NULLs, used by naive orders, never collide).
CREATE UNIQUE INDEX IF NOT EXISTS orders_idempotency_idx ON orders (product_id, idempotency_key);

-- Safe mode: a buyer can own at most one order per sale (backstop for the Redis check).
CREATE UNIQUE INDEX IF NOT EXISTS one_safe_order_per_buyer
    ON orders (product_id, buyer_id) WHERE reservation_id IS NOT NULL;

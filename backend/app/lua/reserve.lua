-- Atomically: check the buyer, check stock, decrement stock, create the reservation.
-- KEYS: stock, reservations (zset), buyer_res, done (set), res hash
-- ARGV: reservation_id, buyer_id, expires_at, amount_cents, hash_ttl
-- Returns {status, reservation_id}: 1 = reserved, 0 = sold out, 2 = already holds one, 3 = already bought
if redis.call('SISMEMBER', KEYS[4], ARGV[2]) == 1 then return {3, ''} end

local existing = redis.call('GET', KEYS[3])
if existing then return {2, existing} end

local stock = tonumber(redis.call('GET', KEYS[1]) or '0')
if stock <= 0 then return {0, ''} end

redis.call('DECR', KEYS[1])
redis.call('ZADD', KEYS[2], ARGV[3], ARGV[1])
redis.call('SET', KEYS[3], ARGV[1])
redis.call('HSET', KEYS[5], 'buyer', ARGV[2], 'amount', ARGV[4], 'paid', '0')
redis.call('EXPIRE', KEYS[5], ARGV[5])
return {1, ARGV[1]}

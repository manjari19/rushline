-- Turn a live, paid reservation into "sold": remove it WITHOUT returning stock.
-- ZREM is the atomic gate: either this script or the expiry sweep removes a reservation, never both.
-- KEYS: reservations (zset), buyer_res, res hash, done (set)
-- ARGV: reservation_id, buyer_id, now
-- Returns: 1 = consumed, 0 = gone, -1 = expired, -2 = not paid
local expires_at = redis.call('ZSCORE', KEYS[1], ARGV[1])
if not expires_at then return 0 end
if tonumber(expires_at) <= tonumber(ARGV[3]) then return -1 end
if redis.call('HGET', KEYS[3], 'paid') ~= '1' then return -2 end

redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('DEL', KEYS[2])
redis.call('DEL', KEYS[3])
redis.call('SADD', KEYS[4], ARGV[2])
return 1

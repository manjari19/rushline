-- Flag a still-live reservation as paid.
-- KEYS: reservations (zset), res hash
-- ARGV: reservation_id, now
-- Returns 1 if marked, 0 if the reservation is gone or expired.
local expires_at = redis.call('ZSCORE', KEYS[1], ARGV[1])
if not expires_at or tonumber(expires_at) <= tonumber(ARGV[2]) then return 0 end
redis.call('HSET', KEYS[2], 'paid', '1')
return 1

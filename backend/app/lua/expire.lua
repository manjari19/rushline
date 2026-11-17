-- Return stock from expired reservations (the worker calls this every tick).
-- KEYS: reservations (zset), stock
-- ARGV: now, batch_limit, sale_prefix
local ids = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2])
for _, rid in ipairs(ids) do
    local hash_key = ARGV[3] .. 'res:' .. rid
    local buyer = redis.call('HGET', hash_key, 'buyer')
    redis.call('ZREM', KEYS[1], rid)
    redis.call('INCR', KEYS[2])
    if buyer then redis.call('DEL', ARGV[3] .. 'buyer_res:' .. buyer) end
    redis.call('DEL', hash_key)
end
return #ids

-- Waiting room: pop the next N buyers from the queue and mark them admitted.
-- KEYS: queue (zset)
-- ARGV: count, admitted_key_prefix, ttl_seconds
local popped = redis.call('ZPOPMIN', KEYS[1], ARGV[1])
local admitted = 0
for i = 1, #popped, 2 do
    redis.call('SET', ARGV[2] .. popped[i], '1', 'EX', ARGV[3])
    admitted = admitted + 1
end
return admitted

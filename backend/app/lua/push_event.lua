-- Append an activity event. Consecutive "rejected" (sold out) events are merged into the newest
-- entry (its `units` counts the buyers), so a flood of sold-out buyers is one row, not thousands.
-- KEYS: events list
-- ARGV: entry_json, max_events, event_type, ts, buyer_id
if ARGV[3] == 'rejected' then
    local head = redis.call('LINDEX', KEYS[1], 0)
    if head then
        local entry = cjson.decode(head)
        if entry.event == 'rejected' then
            entry.units = entry.units + 1
            entry.ts = tonumber(ARGV[4])
            entry.buyer_id = ARGV[5]
            redis.call('LSET', KEYS[1], 0, cjson.encode(entry))
            return 1
        end
    end
end
redis.call('LPUSH', KEYS[1], ARGV[1])
redis.call('LTRIM', KEYS[1], 0, tonumber(ARGV[2]) - 1)
return 1

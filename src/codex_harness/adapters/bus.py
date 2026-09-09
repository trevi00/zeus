import json

from redis import Redis
from redis.exceptions import ResponseError

from codex_harness.adapters.contracts import validate_message
from codex_harness.domain.model import canonical


class RedisBus:
    # INV-MESSAGE-001: group inspection and deletion must be atomic so pending
    # and not-yet-delivered payloads remain available for at-least-once delivery.
    _COMPACT_SCRIPT = """
local function parts(id)
    if type(id) ~= 'string' then error('Invalid stream ID metadata') end
    local ms, seq = string.match(id, '^(%d+)%-(%d+)$')
    if not ms then error('Invalid stream ID metadata') end
    return ms, seq
end
local function decimal_less(a, b)
    if #a ~= #b then return #a < #b end
    return a < b
end
local function id_less(a, b)
    -- IDs contain unsigned 64-bit components; Lua numbers lose precision above 2^53.
    local am, as = parts(a)
    local bm, bs = parts(b)
    if am ~= bm then return decimal_less(am, bm) end
    return decimal_less(as, bs)
end
local boundary = nil
local function protect(id)
    parts(id)
    if not boundary or id_less(id, boundary) then boundary = id end
end
local key = KEYS[1]
local retain = tonumber(ARGV[1])
local length = redis.call('XLEN', key)
if length == 0 or length <= retain then return 0 end
local groups = redis.call('XINFO', 'GROUPS', key)
if #groups == 0 then return 0 end
if retain > 0 then
    local newest = redis.call('XREVRANGE', key, '+', '-', 'COUNT', ARGV[1])
    protect(newest[#newest][1])
end
for _, group in ipairs(groups) do
    local name, delivered
    for i = 1, #group, 2 do
        if group[i] == 'name' then name = group[i + 1] end
        if group[i] == 'last-delivered-id' then delivered = group[i + 1] end
    end
    if type(name) ~= 'string' then error('Invalid consumer group metadata') end
    -- INV-MESSAGE-001: keep the delivered boundary itself, plus all later IDs.
    protect(delivered)
    local pending = redis.call('XPENDING', key, name, '-', '+', 1)
    if #pending > 0 then protect(pending[1][1]) end
end
-- All metadata is validated before the sole mutation. Redis 7.4 in compose.yaml
-- supports exact MINID trimming (available since 6.2); do not use approximate trim.
return redis.call('XTRIM', key, 'MINID', '=', boundary)
"""

    def __init__(self, url: str, namespace: str | None = None):
        from codex_harness.adapters.configuration import settings

        self.client = Redis.from_url(url, decode_responses=True, socket_timeout=10)
        self.namespace = namespace if namespace is not None else settings().get(
            "HARNESS_REDIS_NAMESPACE", "codex-harness")

    def stream(self, agent: str) -> str:
        return f"{self.namespace}:agent:{agent}"

    def publish(self, message: dict) -> str:
        validate_message(message)
        return self.client.xadd(self.stream(message["who"]["recipient"]), {"body": canonical(message)})

    def ensure_group(self, agent: str) -> None:
        try:
            self.client.xgroup_create(self.stream(agent), "workers", id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def receive(self, agent: str, consumer: str, idle_ms: int = 60000) -> tuple | None:
        self.ensure_group(agent)
        # Recover messages left unacknowledged by a dead consumer before new delivery.
        reclaimed = self.client.xautoclaim(self.stream(agent), "workers", consumer,
                                         idle_ms, start_id="0-0", count=1)
        if reclaimed[1]:
            return reclaimed[1][0]
        rows = self.client.xreadgroup("workers", consumer, {self.stream(agent): ">"},
                                     count=1, block=1000)
        return rows[0][1][0] if rows else None

    def ack(self, agent: str, entry_id: str) -> None:
        self.client.xack(self.stream(agent), "workers", entry_id)

    def compact(self, agent: str, retain: int = 1000) -> int:
        """Reclaim a safe prefix; stalled groups can prevent any reclamation.

        Keep at least the newest ``retain`` entries and all existing groups'
        pending and undelivered payloads. Streams without groups are left alone.
        """
        if isinstance(retain, bool) or not isinstance(retain, int) or retain < 0:
            raise ValueError("retain must be a nonnegative integer")
        # Redis COUNT accepts signed 64-bit integers. Larger retention floors
        # cannot require trimming a stream (XLEN also returns a signed integer).
        count = min(retain, 2**63 - 1)
        return int(self.client.eval(self._COMPACT_SCRIPT, 1, self.stream(agent), count))

    def dead_letter(self, agent: str, entry_id: str, fields: dict, reason: str) -> None:
        self.client.xadd(f"{self.namespace}:dead-letter", {
            "source": self.stream(agent), "entry_id": entry_id,
            "body": fields.get("body", ""), "reason": reason,
        })
        self.ack(agent, entry_id)

    @staticmethod
    def decode(fields: dict) -> dict:
        return validate_message(json.loads(fields["body"]))

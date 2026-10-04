"""The Redis-stream message bus: run-scoped namespaces, the transport incarnation identity,
group delivery with reclaim, dead-letter and safe compaction.

Layer: adapters
Context: storage
Owns: the `<namespace>:agent:<id>` streams, the `workers` group, `<namespace>:dead-letter` and the
`<namespace>:transport-incarnation` token
Does not own: the outbox that commits a transport before publishing (coordination); message shape
Entry points: RedisBus, RedisBus.for_run, run_namespace, TRANSPORT_SCHEMA
Contracts: INV-MESSAGE-001

The namespace is always given by the caller: reading `HARNESS_REDIS_NAMESPACE` is host settings, so
composition supplies it (M7 read it here when no namespace was passed). The storage token is minted
by the injected id source.
"""

import hashlib
import json

from redis import Redis
from redis.exceptions import RedisError, ResponseError

from codex_harness.kernel.ids import SYSTEM_IDS, canonical, digest
from codex_harness.kernel.ports import IdSource
from codex_harness.storage.adapters.message_schema import validate_message
from codex_harness.storage.ports import MessageDeliveryError, TransportChanged

TRANSPORT_SCHEMA = "urn:zeus:transport:redis-stream:1"
RUN_SCOPE = "run"


def run_namespace(prefix: str, run_id: str) -> str:
    """The deterministic run-scoped namespace (SPEC "Real council progress: isolated delivery"): the
    configured namespace stays the prefix and a bounded digest of the run id is appended, so every
    publisher and consumer of ONE run shares its streams, two runs never compete for one role queue
    and a restart of the same run id derives the same streams. The run id itself never reaches Redis
    keys, so no caller text is interpolated there."""
    if not (isinstance(prefix, str) and prefix and isinstance(run_id, str) and run_id):
        raise ValueError("run namespace needs a configured prefix and a run id")
    return f"{prefix}:{RUN_SCOPE}:{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:32]}"


class RedisBus:
    # INV-MESSAGE-001, RSM G2: the dead-letter record and the acknowledgement are one atomic step.
    # KEYS[1] dead-letter stream, KEYS[2] source stream; ARGV source, entry_id, body, reason.
    _DEAD_LETTER_SCRIPT = """
redis.call('XADD', KEYS[1], '*', 'source', ARGV[1], 'entry_id', ARGV[2], 'body', ARGV[3], 'reason', ARGV[4])
redis.call('XACK', KEYS[2], 'workers', ARGV[2])
return 1
"""

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

    # research-dispatch-recovery-001: the storage check and the write are ONE atomic script, so a
    # replaced, reset or different server behind the committed endpoint refuses without writing.
    _PUBLISH_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return false end
return redis.call('XADD', KEYS[2], '*', 'body', ARGV[2])
"""

    def __init__(self, url: str, namespace: str, *, ids: IdSource | None = None):
        if not isinstance(namespace, str) or not namespace:
            raise ValueError("the Redis namespace is a required, non-empty setting")
        self.client = Redis.from_url(url, decode_responses=True, socket_timeout=10)
        self.namespace = namespace
        self.ids = ids or SYSTEM_IDS
        # Credential-free location from the parsed URL: host/port or socket path only, digested, so
        # neither the raw URL, a username nor a password can reach a record, log or evidence.
        kwargs = self.client.connection_pool.connection_kwargs
        location = {"path": str(kwargs["path"])} if kwargs.get("path") else \
            {"host": str(kwargs.get("host")), "port": int(kwargs.get("port") or 6379)}
        self._endpoint, self._database = digest(location), int(kwargs.get("db") or 0)
        # SPEC "Council isolation resubmission": the unscoped bus names no run route; the outbox relay
        # leaves every pinned run message pending for its owner instead of publishing it here.
        self.route = None

    @classmethod
    def for_run(cls, url: str, run_id: str, namespace: str, *, ids: IdSource | None = None):
        """The bus of ONE autonomous run: the configured (or given) namespace as prefix, scoped by
        `run_namespace`. Existing global consumers keep constructing the unscoped bus. `route` is the
        trusted adapter configuration the run owner pins durably and every relay checks."""
        bus = cls(url, namespace, ids=ids)
        bus.namespace = run_namespace(bus.namespace, run_id)
        bus.route = {"scope": RUN_SCOPE, "run_id": run_id, "namespace": bus.namespace}
        return bus

    def stream(self, agent: str) -> str:
        return f"{self.namespace}:agent:{agent}"

    def incarnation_key(self) -> str:
        return f"{self.namespace}:transport-incarnation"

    def transport(self, create: bool = True) -> dict:
        """The credential-free identity of THIS bus (research-dispatch-recovery-001): endpoint digest,
        database, namespace, the server process `run_id` and a random storage token kept in the
        namespace. The publisher creates the token once (`SET NX`); a probe passes `create=False` and
        reads a missing token as None, never inventing one.

        What it establishes: equal identities mean the same endpoint text, database and namespace
        on a server process that was not restarted, whose namespace still holds the token written
        by the first publisher. What it cannot establish: that stream entries were not deleted or
        trimmed, or that a snapshot restore did not replace the data under the same process; a
        restart, a token loss or an alias of the same server under another endpoint reads as a
        different identity, so recovery refuses rather than proving continuity."""
        key = self.incarnation_key()
        try:
            if create:
                self.client.set(key, self.ids.uuid4().hex, nx=True)
            storage = self.client.get(key)
            server = (self.client.info("server") or {}).get("run_id")
        except RedisError as exc:
            raise MessageDeliveryError(type(exc).__name__) from exc
        return {"schema": TRANSPORT_SCHEMA, "endpoint_sha256": self._endpoint, "database": self._database,
                "namespace": self.namespace, "server": server if isinstance(server, str) and server else None,
                "storage": storage if isinstance(storage, str) and storage else None}

    @staticmethod
    def validate(message: dict) -> dict:
        return validate_message(message)

    def publish(self, message: dict, transport: dict | None = None) -> str:
        """Without `transport` the legacy unbound XADD. With the identity the outbox committed for
        this attempt, the bus rechecks its own static identity and server process, then publishes
        through the atomic storage check; any mismatch raises `TransportChanged` before a write."""
        self.validate(message)
        stream, body = self.stream(message["who"]["recipient"]), canonical(message)
        if transport is None:
            try:
                return self.client.xadd(stream, {"body": body})
            except RedisError as exc:
                raise MessageDeliveryError(type(exc).__name__) from exc
        static = {"schema": TRANSPORT_SCHEMA, "endpoint_sha256": self._endpoint, "database": self._database,
                  "namespace": self.namespace}
        storage = transport.get("storage") if isinstance(transport, dict) else None
        if not isinstance(storage, str) or not storage or any(transport.get(k) != v for k, v in static.items()):
            raise TransportChanged("transport_changed")
        try:
            if (self.client.info("server") or {}).get("run_id") != transport.get("server"):
                raise TransportChanged("transport_server_changed")
            entry = self.client.eval(self._PUBLISH_SCRIPT, 2, self.incarnation_key(), stream, storage, body)
        except RedisError as exc:
            raise MessageDeliveryError(type(exc).__name__) from exc
        if entry is None:
            raise TransportChanged("transport_storage_changed")
        return entry

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
        # RSM G2, DESIGN-s10 §17a: XADD and XACK run as one server-side step, so a crash can no longer
        # leave the entry pending behind a written record. A reclaim race can still dead-letter one
        # entry twice, so any replay of the dead-letter stream STILL REQUIRES dedup by (source, entry_id).
        self.client.eval(self._DEAD_LETTER_SCRIPT, 2, f"{self.namespace}:dead-letter", self.stream(agent),
                         self.stream(agent), entry_id, fields.get("body", ""), reason)

    @staticmethod
    def decode(fields: dict) -> dict:
        return validate_message(json.loads(fields["body"]))

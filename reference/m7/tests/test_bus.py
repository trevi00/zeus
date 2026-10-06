import json
import os
from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4

import pytest
from redis import Redis as RealRedis
from redis.exceptions import TimeoutError as RedisTimeout

from codex_harness.adapters.bus import TRANSPORT_SCHEMA, RedisBus, run_namespace
from codex_harness.domain.model import envelope
from codex_harness.ports import MessageDeliveryError, TransportChanged

SECRET = "s3cret-CANARY-credential"


@pytest.mark.parametrize("retain", [-1, 1.0, "1", None, True, False, [], float("inf")])
def test_compact_rejects_invalid_retention_before_accessing_redis(retain):
    bus = RedisBus("redis://localhost:6379")
    bus.client = Mock()
    with pytest.raises(ValueError, match="nonnegative integer"):
        bus.compact("worker", retain)
    assert bus.client.mock_calls == []


# ----- transport identity (research-dispatch-recovery-001) ---------------------------------------------------
class FakeRedisServer:
    """LABELLED in-memory stand-in for ONE Redis server process: per-database strings and streams,
    its `run_id`, and the atomic publish script emulated by identity. It is not a Redis observation.
    `lose_reply` is a LABELLED injected fault: the XADD lands, then the reply is lost (a timeout);
    `fail_before` raises the timeout on every command; `fail_write` only on the publish script, before
    its write."""

    def __init__(self, run_id="run-a"):
        self.run_id, self.databases, self.sequence = run_id, {}, 0
        self.lose_reply = self.fail_before = self.fail_write = False

    def database(self, number):
        return self.databases.setdefault(number, {"strings": {}, "streams": {}})

    def restart(self, run_id):
        self.run_id = run_id   # data kept (persistence); the process incarnation changed

    def flush(self):
        self.databases = {}


class FakeRedisClient:
    """One connection to a FakeRedisServer database. `connection_pool` is the REAL redis-py pool parsed
    from the URL (no network), so RedisBus derives its endpoint exactly as in production."""

    def __init__(self, server, number, pool):
        self.server, self.number, self.connection_pool = server, number, pool

    @property
    def data(self):
        return self.server.database(self.number)

    def _fault(self):
        if self.server.fail_before:
            raise RedisTimeout("fixture: timeout before write")

    def set(self, key, value, nx=False):
        self._fault()
        if nx and key in self.data["strings"]:
            return None
        self.data["strings"][key] = value
        return True

    def get(self, key):
        self._fault()
        return self.data["strings"].get(key)

    def info(self, section=None):
        self._fault()
        return {"run_id": self.server.run_id}

    def xadd(self, stream, fields):
        self._fault()
        self.server.sequence += 1
        entry = str(self.server.sequence) + "-0"
        self.data["streams"].setdefault(stream, []).append((entry, dict(fields)))
        if self.server.lose_reply:
            raise RedisTimeout("fixture: reply lost after write")
        return entry

    def eval(self, script, numkeys, *args):
        assert script == RedisBus._PUBLISH_SCRIPT and numkeys == 2, "only the publish script is emulated"
        token_key, stream, token, body = args
        self._fault()
        if self.server.fail_write:
            raise RedisTimeout("fixture: timeout before write")
        if self.data["strings"].get(token_key) != token:
            return None
        return self.xadd(stream, {"body": body})

    def xlen(self, stream):
        self._fault()
        return len(self.data["streams"].get(stream, []))

    def xrange(self, stream, count):
        self._fault()
        return list(self.data["streams"].get(stream, []))[:count]

    # LABELLED minimal consumer-group emulation (one group per stream): `>` delivers the next
    # undelivered entry and records it pending for that consumer; nothing is ever idle long enough to
    # be auto-claimed; XACK removes it from pending. It is not a Redis observation.
    def _group(self, stream):
        return self.data.setdefault("groups", {}).get(stream)

    def xgroup_create(self, stream, group, id="0", mkstream=False):
        from redis.exceptions import ResponseError
        self._fault()
        if self._group(stream) is not None:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self.data["streams"].setdefault(stream, [])
        self.data.setdefault("groups", {})[stream] = {"name": group, "delivered": 0, "pending": {}}

    def xautoclaim(self, stream, group, consumer, idle_ms, start_id="0-0", count=1):
        self._fault()
        return ["0-0", []]

    def xreadgroup(self, group, consumer, streams, count=1, block=None):
        self._fault()
        [(stream, cursor)] = streams.items()
        state, entries = self._group(stream), self.data["streams"].get(stream, [])
        if cursor != ">" or state["delivered"] >= len(entries):
            return []
        entry = entries[state["delivered"]]
        state["delivered"] += 1
        state["pending"][entry[0]] = consumer
        return [[stream, [entry]]]

    def xack(self, stream, group, entry_id):
        self._fault()
        return 1 if self._group(stream)["pending"].pop(entry_id, None) is not None else 0


class FakeRedisFactory:
    """LABELLED replacement for `redis.Redis` in the bus module: `from_url` parses the URL with the
    real redis-py and connects to the fixture server registered for that host and port."""

    def __init__(self, servers):
        self.servers = servers

    def from_url(self, url, **kwargs):
        pool = RealRedis.from_url(url, **kwargs).connection_pool
        location = pool.connection_kwargs
        server = self.servers[(location["host"], int(location["port"]))]
        return FakeRedisClient(server, int(location.get("db") or 0), pool)


def bus_on(monkeypatch, servers, url, namespace="ns"):
    monkeypatch.setattr("codex_harness.adapters.bus.Redis", FakeRedisFactory(servers))
    return RedisBus(url, namespace=namespace)


def message():
    return envelope("task.assign", "conductor", "lead:improvement", "plan", {"objective": "Bus unit test"}, "c-1")


def test_identity_is_credential_free_and_the_probe_never_creates_the_storage_token(monkeypatch):
    server = FakeRedisServer()
    bus = bus_on(monkeypatch, {("a.example", 6379): server}, "redis://owner:" + SECRET + "@a.example:6379/3")
    probed = bus.transport(create=False)
    assert probed["storage"] is None and server.database(3)["strings"] == {}, "a probe writes nothing"
    bound = bus.transport()
    assert bound == {**probed, "storage": bound["storage"]} and bound["schema"] == TRANSPORT_SCHEMA
    assert bound["database"] == 3 and bound["namespace"] == "ns" and bound["server"] == "run-a"
    assert bus.transport() == bound, "the token is created once and then only read"
    text = json.dumps(bound)
    assert SECRET not in text and "owner" not in text and "a.example" not in text


def test_bound_publish_writes_only_on_the_committed_transport(monkeypatch):
    servers = {("a.example", 6379): FakeRedisServer("run-a"), ("b.example", 6379): FakeRedisServer("run-b")}
    a = bus_on(monkeypatch, servers, "redis://a.example:6379/0")
    binding = a.transport()
    assert a.publish(message(), transport=binding) == "1-0"
    stream = a.stream("lead:improvement")

    def refused(bus, bound):
        before = deepcopy([s.databases for s in servers.values()])
        with pytest.raises(TransportChanged):
            bus.publish(message(), transport=bound)
        assert [s.databases for s in servers.values()] == before, "refused before any write"

    refused(bus_on(monkeypatch, servers, "redis://b.example:6379/0"), binding)            # another endpoint
    refused(bus_on(monkeypatch, servers, "redis://a.example:6379/1"), binding)            # another database
    refused(bus_on(monkeypatch, servers, "redis://a.example:6379/0", "other"), binding)   # another namespace
    refused(a, {**binding, "storage": None})
    servers[("a.example", 6379)].restart("run-a2")
    refused(a, binding)                                                                    # restarted process
    servers[("a.example", 6379)].restart("run-a")
    servers[("a.example", 6379)].database(0)["strings"][a.incarnation_key()] = "reset-token"
    refused(a, binding)                                                                    # storage replaced
    assert len(servers[("a.example", 6379)].database(0)["streams"][stream]) == 1


def test_legacy_publish_and_transport_errors_keep_the_delivery_error_contract(monkeypatch):
    server = FakeRedisServer()
    bus = bus_on(monkeypatch, {("a.example", 6379): server}, "redis://a.example:6379/0")
    assert bus.publish(message()) == "1-0", "an unbound publish is the unchanged legacy XADD"
    binding = bus.transport()
    server.lose_reply = True
    with pytest.raises(MessageDeliveryError):
        bus.publish(message(), transport=binding)
    assert len(server.database(0)["streams"][bus.stream("lead:improvement")]) == 2, "the lost reply still wrote"
    server.lose_reply, server.fail_before = False, True
    with pytest.raises(MessageDeliveryError):
        bus.transport()


# ----- run-scoped delivery (SPEC "Real council progress: isolated delivery", 2026-09-24) -----------------
def assignment(run_id, recipient="lead:researcher"):
    """A role assignment of ONE autonomous run (exact correlation `autonomous:<run>`)."""
    return envelope("task.assign", "conductor", recipient, "dge_role", {"role": "researcher"}, "autonomous:" + run_id)


def drain(bus, agent, consumer):
    """What one run's drain consumer actually receives, ACKing each entry (the real RedisBus calls)."""
    seen = []
    while (row := bus.receive(agent, consumer)) is not None:
        seen.append(bus.decode(row[1])["correlation_id"])
        bus.ack(agent, row[0])
    return seen


def test_the_run_namespace_is_deterministic_bounded_prefixed_and_carries_no_run_text():
    a, again, b = run_namespace("ns", "run-A.c001"), run_namespace("ns", "run-A.c001"), run_namespace("ns", "run-B.c001")
    assert a == again and a != b and a.startswith("ns:run:") and b.startswith("ns:run:")
    assert len(a) == len("ns:run:") + 32 and "run-A" not in a
    assert run_namespace("other", "run-A.c001") != a, "the configured namespace stays the prefix"
    for prefix, run_id in (("", "r"), ("ns", ""), (None, "r"), ("ns", None)):
        with pytest.raises(ValueError):
            run_namespace(prefix, run_id)


def test_two_run_buses_interleaved_never_steal_and_the_old_global_stream_is_untouched(monkeypatch):
    """Discriminating regression over the REAL RedisBus publish/receive/ack code on a LABELLED fixture
    server: two runs with identical agents and different run ids, assignments interleaved. The control
    (the old unscoped bus of both runs) shows the stealing this change removes."""
    server = FakeRedisServer()
    servers = {("a.example", 6379): server}
    url = "redis://a.example:6379/0"
    legacy = bus_on(monkeypatch, servers, url)
    old = legacy.publish(assignment("old-run"))           # retained evidence on the shared stream
    legacy.ensure_group("lead:researcher")

    # Control: both runs on the one global namespace -> run A's consumer receives run B's assignment.
    control_a, control_b = bus_on(monkeypatch, servers, url), bus_on(monkeypatch, servers, url)
    control_b.publish(assignment("run-B"))
    control_a.publish(assignment("run-A"))
    assert drain(control_a, "lead:researcher", "lead:researcher:autonomous") == \
        ["autonomous:old-run", "autonomous:run-B", "autonomous:run-A"]
    before = deepcopy(server.database(0))

    monkeypatch.setattr("codex_harness.adapters.bus.Redis", FakeRedisFactory(servers))
    a, b = RedisBus.for_run(url, "run-A", namespace="ns"), RedisBus.for_run(url, "run-B", namespace="ns")
    for bus, run_id in ((a, "run-A"), (b, "run-B"), (a, "run-A"), (b, "run-B")):
        bus.publish(assignment(run_id), transport=bus.transport())
    assert drain(a, "lead:researcher", "lead:researcher:autonomous") == ["autonomous:run-A"] * 2
    assert drain(b, "lead:researcher", "lead:researcher:autonomous") == ["autonomous:run-B"] * 2
    assert a.transport()["namespace"] == a.namespace != b.transport()["namespace"], "the binding names the run scope"

    restarted = RedisBus.for_run(url, "run-A", namespace="ns")
    assert restarted.stream("lead:researcher") == a.stream("lead:researcher"), "a restart derives the same streams"
    assert restarted.route == a.route == {"scope": "run", "run_id": "run-A", "namespace": a.namespace} != b.route
    assert legacy.route is None, "the unscoped bus names no run route and cannot own a pin"
    assert restarted.transport(create=False) == a.transport(create=False)
    after = server.database(0)
    global_keys = (legacy.stream("lead:researcher"), legacy.incarnation_key())
    assert {k: after["streams"].get(k) for k in global_keys} == {k: before["streams"].get(k) for k in global_keys}
    assert after["groups"][legacy.stream("lead:researcher")] == before["groups"][legacy.stream("lead:researcher")]
    assert after["streams"][legacy.stream("lead:researcher")][0][0] == old, \
        "the old shared entry is retained, never moved, deleted or republished elsewhere"


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("HARNESS_INTEGRATION") != "1", reason="Set HARNESS_INTEGRATION=1 for local services")
def test_real_redis_run_scoped_buses_interleave_without_stealing_and_leave_the_global_stream():
    """Actual disposable Redis namespace (HARNESS_INTEGRATION=1): the same interleaving on real streams
    and consumer groups; every key under the random prefix is removed afterwards."""
    from codex_harness.bootstrap import redis_url
    prefix = "zeus-run-scope-test-" + uuid4().hex
    legacy = RedisBus(redis_url(), namespace=prefix)
    a, b = RedisBus.for_run(redis_url(), "run-A", namespace=prefix), RedisBus.for_run(redis_url(), "run-B", namespace=prefix)
    try:
        old = legacy.publish(assignment("old-run"))
        legacy.ensure_group("lead:researcher")
        for bus, run_id in ((a, "run-A"), (b, "run-B"), (a, "run-A"), (b, "run-B")):
            bus.publish(assignment(run_id), transport=bus.transport())
        assert drain(a, "lead:researcher", "c-a") == ["autonomous:run-A"] * 2
        assert drain(b, "lead:researcher", "c-b") == ["autonomous:run-B"] * 2
        assert [entry[0] for entry in legacy.client.xrange(legacy.stream("lead:researcher"))] == [old]
        assert legacy.client.xpending(legacy.stream("lead:researcher"), "workers")["pending"] == 0
    finally:
        for key in list(legacy.client.scan_iter(match=prefix + ":*")):
            legacy.client.delete(key)

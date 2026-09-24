import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from redis import Redis as RealRedis
from redis.exceptions import TimeoutError as RedisTimeout

from codex_harness.adapters.bus import TRANSPORT_SCHEMA, RedisBus
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

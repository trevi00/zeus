"""REDIS-STREAMS G3: `RedisStreamFacts` rows from an in-memory fake client (exact values, per-scope failure, no secrets, renderable) and, gated on
`HARNESS_REDIS_URL`, from a real Redis namespace."""
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from codex_harness.kernel.message import envelope
from codex_harness.observation.adapters import metrics_exposition
from codex_harness.observation.adapters.redis_stream_facts import RedisStreamFacts
from codex_harness.storage.adapters.redis_bus import RedisBus

PASSWORD = "s3cretFixturePw"
URL = "redis://" + "user:" + PASSWORD + "@redis.invalid:6379/0"  # assembled, so no credential-shaped literal is committed
NAMESPACE = "ns-secret-namespace"
FAMILIES = {
    "zeus_redis_stream_entries", "zeus_redis_stream_pending", "zeus_redis_stream_lag", "zeus_redis_pending_oldest_idle_seconds",
    "zeus_redis_dead_letter_entries", "zeus_redis_memory_used_bytes", "zeus_redis_memory_max_bytes", "zeus_redis_facts_available",
}


class FakeClient:
    def __init__(self, streams, dead_letters=0, memory=None, fail=()):
        self.streams, self.dead_letters, self.fail = streams, dead_letters, set(fail)
        self.memory = {"used_memory": 4096, "maxmemory": 8192} if memory is None else memory
        self.connection_pool = SimpleNamespace(connection_kwargs={})

    def _check(self, key):
        if key in self.fail:
            raise ConnectionError("boom " + URL + key)

    def exists(self, key):
        self._check(key)
        return key.endswith("dead-letter") and self.dead_letters > 0 or key in self.streams

    def xlen(self, key):
        self._check(key)
        return self.dead_letters if key.endswith("dead-letter") else self.streams[key]["entries"]

    def xinfo_groups(self, key):
        return self.streams[key]["groups"]

    def xpending_range(self, key, group, min, max, count):
        assert (group, min, max) == ("workers", "-", "+")
        return [{"message_id": f"{i}-0", "consumer": "c", "time_since_delivered": idle, "times_delivered": 1}
                for i, idle in enumerate(self.streams[key]["idle"][:count])]

    def info(self, section=None):
        assert section == "memory"
        self._check("info")
        return self.memory


class FakeBus:
    namespace = NAMESPACE

    def __init__(self, client):
        self.client = client

    def stream(self, agent):
        return f"{self.namespace}:agent:{agent}"


def streams():
    return {
        f"{NAMESPACE}:agent:conductor": {"entries": 7, "idle": [5000, 120000],
                                         "groups": [{"pending": 2, "lag": 3}, {"pending": 0, "lag": 1}]},
        f"{NAMESPACE}:agent:worker": {"entries": 4, "idle": [], "groups": [{"pending": 0, "lag": None}]},
    }


def facts(client, **kwargs):
    return RedisStreamFacts(url=URL, agents=["conductor", "worker"], bus_factory=lambda url: FakeBus(client), **kwargs)


def flat(rows):
    return {(row["metric"], tuple(item["labels"])): item["value"] for row in rows for item in row["series"]}


def test_exact_values_for_two_agents_and_the_server():
    got = flat(facts(FakeClient(streams(), dead_letters=5)).rows())
    assert got == {
        ("zeus_redis_stream_entries", ("conductor",)): 7, ("zeus_redis_stream_entries", ("worker",)): 4,
        ("zeus_redis_stream_pending", ("conductor",)): 2, ("zeus_redis_stream_pending", ("worker",)): 0,
        ("zeus_redis_stream_lag", ("conductor",)): 4,
        ("zeus_redis_pending_oldest_idle_seconds", ("conductor",)): 120.0,
        ("zeus_redis_dead_letter_entries", ()): 5,
        ("zeus_redis_memory_used_bytes", ()): 4096, ("zeus_redis_memory_max_bytes", ()): 8192,
        ("zeus_redis_facts_available", ("conductor",)): 1, ("zeus_redis_facts_available", ("worker",)): 1,
        ("zeus_redis_facts_available", ("server",)): 1,
    }


def test_missing_dead_letter_stream_is_zero_and_the_idle_sample_is_bounded():
    got = flat(facts(FakeClient(streams()), pending_sample=1).rows())
    assert got[("zeus_redis_dead_letter_entries", ())] == 0
    assert got[("zeus_redis_pending_oldest_idle_seconds", ("conductor",))] == 5.0
    with pytest.raises(ValueError):
        facts(FakeClient(streams()), pending_sample=0)


def test_a_failing_agent_read_drops_only_that_agent():
    got = flat(facts(FakeClient(streams(), fail={f"{NAMESPACE}:agent:conductor"})).rows())
    assert got[("zeus_redis_facts_available", ("conductor",))] == 0
    assert not [key for key in got if key[1] == ("conductor",) and key[0] != "zeus_redis_facts_available"]
    assert got[("zeus_redis_facts_available", ("worker",))] == 1 and got[("zeus_redis_stream_entries", ("worker",))] == 4
    assert got[("zeus_redis_facts_available", ("server",))] == 1


def test_a_failing_server_read_drops_dead_letters_and_memory_only():
    got = flat(facts(FakeClient(streams(), fail={"info"})).rows())
    assert got[("zeus_redis_facts_available", ("server",))] == 0
    assert not [key for key in got if key[0] in {"zeus_redis_dead_letter_entries", "zeus_redis_memory_used_bytes", "zeus_redis_memory_max_bytes"}]
    assert got[("zeus_redis_stream_entries", ("conductor",))] == 7 and got[("zeus_redis_facts_available", ("conductor",))] == 1


def test_an_unbuildable_bus_makes_every_scope_unavailable():
    def refuse(url):
        raise ConnectionError(url)
    got = flat(RedisStreamFacts(url=URL, agents=["conductor", "worker"], bus_factory=refuse).rows())
    assert got == {("zeus_redis_facts_available", (scope,)): 0 for scope in ("conductor", "worker", "server")}


def test_unlimited_maxmemory_leaves_the_max_gauge_absent():
    got = flat(facts(FakeClient(streams(), memory={"used_memory": 10, "maxmemory": 0})).rows())
    assert ("zeus_redis_memory_max_bytes", ()) not in got and got[("zeus_redis_memory_used_bytes", ())] == 10
    assert got[("zeus_redis_facts_available", ("server",))] == 1


def test_no_secret_or_key_name_reaches_the_rows_and_labels_are_closed():
    for client in (FakeClient(streams(), dead_letters=1), FakeClient(streams(), fail={f"{NAMESPACE}:agent:worker", "info"})):
        rows = facts(client).rows()
        text = repr(rows)
        for secret in (PASSWORD, "redis.invalid", NAMESPACE, "boom", ":agent:"):
            assert secret not in text
        assert {value for row in rows for item in row["series"] for value in item["labels"]} <= {"conductor", "worker", "server"}


def test_rows_render_with_a_type_line_for_all_eight_families():
    text = metrics_exposition.render(facts(FakeClient(streams())).rows())
    assert {line.split()[2] for line in text.splitlines() if line.startswith("# TYPE ")} == FAMILIES
    assert 'zeus_redis_pending_oldest_idle_seconds{agent="conductor"} 120.0' in text


@pytest.mark.skipif(not os.environ.get("HARNESS_REDIS_URL"), reason="Set HARNESS_REDIS_URL for a disposable Redis")
def test_real_redis_namespace_entries_pending_idle_and_dead_letters():
    url = os.environ["HARNESS_REDIS_URL"]
    namespace = "zeus-g3-test-" + uuid4().hex
    bus = RedisBus(url, namespace=namespace)
    try:
        for _ in range(3):
            bus.publish(envelope("task.assign", "conductor", "a", "dge_role", {"role": "researcher"}, "g3"))
        bus.ensure_group("a")
        first = bus.receive("a", "c1")
        second = bus.receive("a", "c2")
        bus.dead_letter("a", second[0], second[1], "g3-test")
        assert first is not None
        got = flat(RedisStreamFacts(url=url, agents=["a"], bus_factory=lambda u: RedisBus(u, namespace=namespace)).rows())
        assert got[("zeus_redis_stream_entries", ("a",))] == 3
        assert got[("zeus_redis_stream_pending", ("a",))] >= 1
        assert got[("zeus_redis_pending_oldest_idle_seconds", ("a",))] >= 0
        assert got[("zeus_redis_dead_letter_entries", ())] == 1
        assert got[("zeus_redis_memory_used_bytes", ())] > 0
        assert got[("zeus_redis_facts_available", ("a",))] == got[("zeus_redis_facts_available", ("server",))] == 1
    finally:
        for key in list(bus.client.scan_iter(match=namespace + ":*")):
            bus.client.delete(key)

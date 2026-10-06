"""S11 FLOW-c (DESIGN-s11 §11 R-FLOW): the driving items of F-4 step 5, `host_migration.copy_redis`.

Expected results come from the M7 SOURCE `codex_harness/adapters/host_migration.py:607-627` (and its docstring: "never
REPLACE, never extend an expiry") and INV-HOST-MIGRATION-001 (Redis namespaces preserved, target Redis dedicated); no
expectation is derived from the target. The fake clients are LABELLED fakes implementing only what `copy_redis` calls.
One real-Redis end-to-end node is gated on `HARNESS_REDIS_URL` (the owner runs it at target-integration); the
fake-client tests cover the same branches everywhere.
"""
import os
from uuid import uuid4

import pytest

from codex_harness.delivery.adapters.host_migration import copy_redis
from codex_harness.delivery.domain.host_migration import MigrationRefused

REDIS_URL = os.environ.get("HARNESS_REDIS_URL")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="Set HARNESS_REDIS_URL (target-integration sets it)")
NOW_MS = 1_800_000_000_000


class FakeSource:
    """LABELLED FAKE source: key -> (payload, absolute expiry ms or -1); `dump` of an absent key is None."""

    def __init__(self, data):
        self.data = data
        self.dumped = []

    def dump(self, key):
        self.dumped.append(key)
        return self.data[key][0] if key in self.data else None

    def execute_command(self, name, key):
        assert name == "PEXPIRETIME"
        return self.data[key][1]


class FakeTarget:
    """LABELLED FAKE target: `exists`, `time` (server clock) and `restore` recording every call."""

    def __init__(self, present=(), now_ms=NOW_MS):
        self.present = {key: b"target-" + key.encode() for key in present}
        self.now_ms = now_ms
        self.restores = []

    def exists(self, key):
        return int(key in self.present)

    def time(self):
        return (self.now_ms // 1000, (self.now_ms % 1000) * 1000)

    def restore(self, key, ttl, payload, absttl=False):
        self.restores.append((key, ttl, payload, absttl))
        self.present[key] = payload


def test_an_existing_target_key_is_left_alone_and_counted():
    source = FakeSource({"a": (b"src-a", -1)})
    target = FakeTarget(present=["a"])
    result = copy_redis(source, target, ["a"])
    assert result == {"restored": 0, "already_present": 1, "expired_in_downtime": 0, "keys": 1}
    assert target.restores == []
    assert target.present["a"] == b"target-a"  # M7 :615-617: never REPLACE
    assert source.dumped == []


def test_a_key_gone_from_the_source_is_refused_before_any_later_key():
    source = FakeSource({"c": (b"src-c", -1)})
    target = FakeTarget()
    with pytest.raises(MigrationRefused) as refused:
        copy_redis(source, target, ["gone", "c"])
    assert refused.value.reason_code == "redis_source_missing"  # M7 :618-619
    assert source.dumped == ["gone"]
    assert target.restores == []


def test_expiry_at_or_before_the_target_server_time_is_not_revived():
    source = FakeSource({
        "at": (b"p-at", NOW_MS),
        "before": (b"p-before", NOW_MS - 1),
        "after": (b"p-after", NOW_MS + 1),
    })
    target = FakeTarget()
    result = copy_redis(source, target, ["at", "before", "after"])
    # M7 :622-624: `0 <= expiry <= server_ms(target)` is expired; one millisecond later is restored
    assert result == {"restored": 1, "already_present": 0, "expired_in_downtime": 2, "keys": 3}
    assert target.restores == [("after", NOW_MS + 1, b"p-after", True)]
    assert "at" not in target.present and "before" not in target.present


def test_an_expiry_is_restored_absolute_and_no_expiry_as_zero_without_absttl():
    source = FakeSource({"ttl": (b"p-ttl", NOW_MS + 60_000), "plain": (b"p-plain", -1)})
    target = FakeTarget()
    copy_redis(source, target, ["ttl", "plain"])
    # M7 :625: restore(key, expiry if expiry >= 0 else 0, payload, absttl=expiry >= 0)
    assert target.restores == [("ttl", NOW_MS + 60_000, b"p-ttl", True), ("plain", 0, b"p-plain", False)]


def test_the_spec_example_counts_add_up_to_keys():
    source = FakeSource({
        "a": (b"p-a", -1),
        "b": (b"p-b", NOW_MS + 60_000),
        "c": (b"p-c", NOW_MS - 1),
        "d": (b"p-d", -1),
    })
    target = FakeTarget(present=["d"])
    result = copy_redis(source, target, ["a", "b", "c", "d"])
    assert result == {"restored": 2, "already_present": 1, "expired_in_downtime": 1, "keys": 4}
    assert target.restores == [("a", 0, b"p-a", False), ("b", NOW_MS + 60_000, b"p-b", True)]


def test_a_rerun_after_a_partial_copy_restores_only_the_missing_keys():
    source = FakeSource({"a": (b"p-a", -1), "b": (b"p-b", -1), "c": (b"p-c", -1)})
    target = FakeTarget(present=["a"])  # a partial earlier copy left `a`
    first = copy_redis(source, target, ["a", "b", "c"])
    assert first == {"restored": 2, "already_present": 1, "expired_in_downtime": 0, "keys": 3}
    target.restores.clear()
    second = copy_redis(source, target, ["a", "b", "c"])
    assert second == {"restored": 0, "already_present": 3, "expired_in_downtime": 0, "keys": 3}
    assert target.restores == []


@needs_redis
def test_end_to_end_copy_between_two_logical_databases_of_a_real_redis():
    from redis import ConnectionPool, Redis

    def client(db):
        # redis-py `from_url`: a `db` querystring or URL path wins over the `db=` keyword (the target-integration URL
        # is `unix://.../redis.sock?db=0`), so the keyword alone would put source and target in ONE database
        base = ConnectionPool.from_url(REDIS_URL)
        return Redis(connection_pool=ConnectionPool(connection_class=base.connection_class,
                                                    **{**base.connection_kwargs, "db": db}))

    prefix = f"flowc-{uuid4().hex[:12]}"
    source, target = client(14), client(15)
    assert source.connection_pool.connection_kwargs["db"] == 14 and target.connection_pool.connection_kwargs["db"] == 15
    names = {n: f"{prefix}:{n}" for n in ("plain", "ttl", "present", "dead")}
    try:
        source.set(names["plain"], b"v-plain")
        source.set(names["ttl"], b"v-ttl")
        source.set(names["present"], b"v-source")
        source.set(names["dead"], b"v-dead")
        server_ms = int(source.time()[0]) * 1000
        ttl_at = server_ms + 3_600_000
        source.pexpireat(names["ttl"], ttl_at)
        source.pexpireat(names["dead"], server_ms + 3_000)  # alive now; expires before the copy is observed
        target.set(names["present"], b"v-target")
        keys = [names["plain"], names["ttl"], names["present"]]
        result = copy_redis(source, target, keys)
        assert result == {"restored": 2, "already_present": 1, "expired_in_downtime": 0, "keys": 3}
        assert target.get(names["plain"]) == b"v-plain"
        assert int(target.execute_command("PEXPIRETIME", names["plain"])) == -1
        assert target.get(names["ttl"]) == b"v-ttl"
        assert int(target.execute_command("PEXPIRETIME", names["ttl"])) == ttl_at
        assert target.get(names["present"]) == b"v-target"  # never replaced
        assert target.exists(names["dead"]) == 0  # not named in `keys`: exactly the named keys are copied
        assert copy_redis(source, target, keys) == {
            "restored": 0, "already_present": 3, "expired_in_downtime": 0, "keys": 3}
    finally:
        for name in names.values():
            source.delete(name)
            target.delete(name)

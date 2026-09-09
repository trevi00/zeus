import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from codex_harness.adapters.bus import RedisBus
from codex_harness.adapters.knowledge import PostgresKnowledge
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import database_url, organization, redis_url
from codex_harness.domain.model import ContractError, digest, envelope

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("HARNESS_INTEGRATION") != "1", reason="Set HARNESS_INTEGRATION=1 for local services")]


@pytest.fixture
def pgstore():
    dsn = database_url()
    schema = "test_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    store = PostgresStore(make_conninfo(dsn, options=f"-c search_path={schema},public"))
    store.migrate()
    yield store
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_concurrent_initialization_keeps_extension_outside_private_schemas():
    dsn = database_url()
    schema = "test_" + uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        scoped = make_conninfo(dsn, options=f"-c search_path={schema},public")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: PostgresStore(scoped).migrate(), range(8)))
        with psycopg.connect(scoped) as connection:
            assert connection.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
            extension_schema = connection.execute(
                "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON e.extnamespace=n.oid "
                "WHERE e.extname='vector'").fetchone()[0]
            assert extension_schema == "public"
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT '[1,2]'::public.vector").fetchone()[0] == "[1,2]"


@pytest.fixture
def bus():
    transport = RedisBus(redis_url(), "test-" + uuid4().hex)
    yield transport
    keys = list(transport.client.scan_iter(match=transport.namespace + ":*"))
    if keys:
        transport.client.delete(*keys)


def message(occurrence=None):
    return envelope("incident.report", "worker:implementation", "lead:improvement", "record_incident",
                    {"occurrence_id": occurrence or str(uuid4()), "root_cause": "cause",
                     "scope": "integration", "evidence_refs": ["test:evidence"]}, "integration")


def seed_stream(bus, ids, agent="compact"):
    key = bus.stream(agent)
    for entry_id in ids:
        bus.client.xadd(key, {"body": "payload:" + entry_id}, id=entry_id)
    return key


def read_group(bus, key, group, count=None):
    return bus.client.xreadgroup(group, "reader", {key: ">"}, count=count)[0][1]


@pytest.mark.parametrize("retain,removed", [(0, 1004), (1, 1004), (3, 1002),
                                                  (1005, 0), (10**100, 0), (None, 5)])
def test_bus_compact_retention_and_isolation(bus, retain, removed):
    ids = [f"{n}-0" for n in range(1, 1006)]
    key = seed_stream(bus, ids)
    other = seed_stream(bus, ids, agent="other")
    bus.ensure_group("compact")
    read_group(bus, key, "workers")
    bus.client.xack(key, "workers", *ids)
    result = bus.compact("compact") if retain is None else bus.compact("compact", retain)
    assert result == removed
    assert bus.client.xrange(key) == [(i, {"body": "payload:" + i}) for i in ids[removed:]]
    assert bus.client.xlen(other) == len(ids)
    assert (bus.compact("compact") if retain is None else bus.compact("compact", retain)) == 0


@pytest.mark.parametrize("retain", [0, 1, 3])
def test_bus_compact_preserves_pending_and_undelivered_across_groups(bus, retain):
    ids = [f"{n}-0" for n in range(1, 9)]
    key = seed_stream(bus, ids)
    bus.ensure_group("compact")
    read_group(bus, key, "workers")
    bus.client.xack(key, "workers", *ids)
    bus.client.xgroup_create(key, "slow", id="0")
    assert bus.compact("compact", 0) == 0  # A group that has never read protects everything.
    read_group(bus, key, "slow", count=4)
    bus.client.xack(key, "slow", ids[0], ids[2], ids[3])
    assert bus.compact("compact", retain) == 1
    pending = bus.client.xreadgroup("slow", "reader", {key: "0"})[0][1]
    assert pending == [(ids[1], {"body": "payload:" + ids[1]})]
    bus.client.xack(key, "slow", ids[1])
    assert bus.compact("compact", 0) == 2
    delivered = read_group(bus, key, "slow")
    assert delivered == [(i, {"body": "payload:" + i}) for i in ids[4:]]
    bus.client.xack(key, "slow", *ids[4:])
    assert bus.compact("compact", 0) == 4
    assert bus.client.xrange(key) == [(ids[-1], {"body": "payload:" + ids[-1]})]


def test_bus_compact_preserves_pending_for_every_consumer(bus):
    ids = [f"{n}-0" for n in range(1, 7)]
    key = seed_stream(bus, ids)
    bus.ensure_group("compact")
    read_group(bus, key, "workers", count=3)
    bus.client.xreadgroup("workers", "another-reader", {key: ">"})
    bus.client.xack(key, "workers", ids[0], ids[2], ids[4], ids[5])
    assert bus.compact("compact", 0) == 1
    for consumer, pending_id in [("reader", ids[1]), ("another-reader", ids[3])]:
        assert bus.client.xreadgroup("workers", consumer, {key: "0"})[0][1] == [
            (pending_id, {"body": "payload:" + pending_id})]
    bus.client.xack(key, "workers", ids[1])
    assert bus.compact("compact", 0) == 2
    assert bus.client.xrange(key) == [(i, {"body": "payload:" + i}) for i in ids[3:]]


def test_bus_compact_handles_deleted_delivered_boundary(bus):
    ids = [f"{n}-0" for n in range(1, 7)]
    key = seed_stream(bus, ids)
    bus.ensure_group("compact")
    read_group(bus, key, "workers", count=3)
    bus.client.xack(key, "workers", *ids[:3])
    bus.client.xdel(key, ids[2])
    assert bus.compact("compact", 0) == 2
    assert read_group(bus, key, "workers") == [
        (i, {"body": "payload:" + i}) for i in ids[3:]]


@pytest.mark.parametrize("ids", [
    ["1-0", "9-0", "10-0", "11-0"],
    ["1-0", "1-9", "1-10", "1-11"],
    ["1-0", "9007199254740992-0", "9007199254740993-0", "9007199254740994-0"],
    ["1-0", "2-9007199254740992", "2-9007199254740993", "2-9007199254740994"],
    ["1-0", "18446744073709551614-0", "18446744073709551615-0",
     "18446744073709551615-18446744073709551615"],
])
def test_bus_compact_compares_both_id_components_exactly(bus, ids):
    key = seed_stream(bus, ids)
    bus.ensure_group("compact")
    read_group(bus, key, "workers")
    bus.client.xack(key, "workers", ids[0], *ids[2:])
    # The pending ID is smaller than the retention boundary, even above 2**53.
    assert bus.compact("compact", 2) == 1
    assert [row[0] for row in bus.client.xrange(key)] == ids[1:]
    assert bus.client.xreadgroup("workers", "reader", {key: "0"})[0][1] == [
        (ids[1], {"body": "payload:" + ids[1]})]


def test_bus_compact_missing_empty_and_no_groups(bus):
    assert bus.compact("compact", 0) == 0
    assert not bus.client.exists(bus.stream("compact"))
    bus.ensure_group("compact")
    assert bus.compact("compact", 0) == 0
    key = seed_stream(bus, ["1-0", "2-0"], agent="no-groups")
    assert bus.compact("no-groups", 0) == 0
    assert bus.client.xlen(key) == 2


def test_bus_compact_propagates_redis_errors_without_mutation(bus):
    from redis.exceptions import ResponseError

    key = bus.stream("compact")
    bus.client.set(key, "not a stream")
    with pytest.raises(ResponseError, match="WRONGTYPE"):
        bus.compact("compact", 0)
    assert bus.client.get(key) == "not a stream"


def test_concurrent_second_strike_is_atomic(pgstore):
    service = Harness(pgstore, organization())
    messages = [message() for _ in range(8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(service.record_incident, messages))
    assert sum(r["hook_created"] for r in results) == 1
    with pgstore.transaction() as tx:
        assert len(tx.scan("incidents")) == 8
        assert len(tx.scan("hooks")) == 1
        assert len(tx.scan("outbox")) == 1


def test_real_bus_crash_redelivery_and_outbox(pgstore, bus):
    service = Harness(pgstore, organization())
    msg = message()
    bus.publish(msg)
    entry_id, fields = bus.receive("lead:improvement", "crashed")
    assert service.record_incident(bus.decode(fields))["occurrences"] == 1
    # Simulate a crash after DB commit but before Redis ACK.
    recovered_id, fields = bus.receive("lead:improvement", "replacement", idle_ms=0)
    assert recovered_id == entry_id
    assert service.record_incident(bus.decode(fields))["occurrences"] == 1
    bus.ack("lead:improvement", recovered_id)
    service.record_incident(message())
    assert service.flush_outbox(bus) == 1
    assert service.flush_outbox(bus) == 0
    received_id, fields = bus.receive("conductor", "conductor-test")
    notification = bus.decode(fields)
    assert notification["type"] == "hook.required"
    assert notification["who"]["recipient"] == "conductor"
    bus.ack("conductor", received_id)


def test_canary_state_and_checkpoint_survive_reconnect(pgstore):
    service = Harness(pgstore, organization())
    service.record_incident(message())
    hook_id = service.record_incident(message())["hook_id"]
    spec = {"kind": "executable_alias", "platform": "windows", "match": "codex.ps1", "replacement": "codex.cmd"}
    service.propose(hook_id, "worker:implementation", spec, "abc")
    for actor in ("lead:improvement", "conductor"):
        service.review(hook_id, actor, "abc", digest(spec), True, "test:review")
    service.record_canary(hook_id, "abc", digest(spec), {"reproduction": True, "normal_case": True, "cli_start": True})
    service.activate(hook_id)
    service.checkpoint("worker:implementation", 0, {"next_action": "verify", "source_revision": "abc", "graph_snapshot": "123"})
    restarted = Harness(PostgresStore(pgstore.dsn), organization())
    assert restarted.prepare_command(["codex.ps1"], "windows") == ["codex.cmd"]
    with pytest.raises(ContractError, match="Stale session"):
        restarted.checkpoint("worker:implementation", 0, {"next_action": "old", "source_revision": "abc", "graph_snapshot": "123"})


def test_tree_sitter_graph_vector_and_failed_reindex(pgstore, tmp_path):
    source = tmp_path / "service.py"
    source.write_text("def recover():\n    # @invariant INV-RECOVERY-001\n    return 42\n", encoding="utf-8")
    knowledge = PostgresKnowledge(pgstore.dsn)
    report = knowledge.index_python(str(tmp_path))
    assert report["nodes"] == 3 and report["edges"] == 2
    hits = knowledge.query("recover", depth=1)
    assert {h["kind"] for h in hits} == {"file", "function_definition", "rule_reference"}
    symbol = next(h for h in hits if h["kind"] == "function_definition")
    knowledge.set_embedding(symbol["id"], [1.0, 0.0, 0.0], "test-fixture-v1")
    assert knowledge.vector_query([1.0, 0.0, 0.0], "test-fixture-v1")[0]["id"] == symbol["id"]
    assert knowledge.vector_query([1.0, 0.0, 0.0], "different-model") == []
    source.write_text("def broken(:", encoding="utf-8")
    with pytest.raises(ContractError, match="Parse failed"):
        knowledge.index_python(str(tmp_path))
    assert knowledge.query("recover")


def test_postgres_audit_checkpoint_reconnect_and_stale_write(pgstore, tmp_path):
    from dataclasses import replace

    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.application.research import ResearchAudits
    from codex_harness.application.workflow import Workflow
    from codex_harness.domain.research import PartitionCheckpoint

    workflow = Workflow(pgstore, organization())
    audits = ResearchAudits(pgstore, None, FileArtifacts(str(tmp_path / 'evidence')), workflow)
    with pgstore.transaction() as tx:
        tx.put('research_audits', 'fixture', {'id': 'fixture', 'inventory': [], 'subsystems': ['core']})
    partition = PartitionCheckpoint(**audits.partition('fixture')[0])
    message = envelope('task.assign', 'lead:research', 'worker:github', 'research',
                       {'audit_id': 'fixture', 'partition_id': partition.partition_id}, 'fixture')
    workflow.submit(message)
    task = workflow.claim('worker:github', 'first')
    saved = audits.checkpoint(task, replace(partition, cursor='resume'), [], [])
    reconnected = ResearchAudits(PostgresStore(pgstore.dsn), None, audits.artifacts, workflow)
    assert reconnected.partition('fixture') == [saved]
    with pytest.raises(ContractError, match='Stale partition'):
        reconnected.checkpoint(task, partition, [], [])
    assert reconnected.coverage('fixture')['remaining_subsystems'] == ['core']


def test_postgres_measurement_observations(pgstore, tmp_path):
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.application.measurements import Measurements
    results = Measurements(pgstore, FileArtifacts(str(tmp_path / 'artifacts'))).collect('a' * 40)
    with pgstore.transaction() as tx:
        rows = tx.scan('metric_observations')
    assert len(rows) == 3
    assert {r['metric_id'] for r in rows} == {r['metric_id'] for r in results}
    assert all(r['repository_revision'] == 'a' * 40 for r in rows)


def test_postgres_reverse_progress_concurrency_replay_and_history(pgstore, tmp_path):
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.application.reverse_progress import ReverseProgress

    artifacts = FileArtifacts(str(tmp_path / 'reverse-artifacts'))
    ref = artifacts.put('Integration fixture, not production reverse evidence', 'fixture')['ref']
    source = {'status': 'clean', 'repository': 'fixture', 'commit': 'a' * 40, 'tree': 'b' * 40}

    def attempt(request):
        app = ReverseProgress(PostgresStore(pgstore.dsn), artifacts)
        try:
            return request, app.record('project', '1-A', 'complete', source, [ref], 0, request)
        except ContractError:
            return request, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ['first', 'second']))
    saved = [(request, row) for request, row in outcomes if row is not None]
    assert len(saved) == 1
    request, row = saved[0]
    reconnected = ReverseProgress(PostgresStore(pgstore.dsn), artifacts)
    assert reconnected.record('project', '1-A', 'complete', source, [ref], 0, request) == row
    reconnected.record('project', '1-B', 'complete', source, [ref], 1, 'next')
    reconnected.record('project', '1-A', 'partial', {**source, 'commit': 'c' * 40},
                       [], 2, 'rebaseline', rebaseline=True)
    with pgstore.transaction() as tx:
        history = tx.scan('reverse_history')
        assert {r['generation'] for r in history} == {1, 2, 3}
        assert tx.get('reverse_progress', 'project')['source']['commit'] == 'c' * 40
        assert next(r for r in history if r['generation'] == 2)['releases']['1-B']['status'] == 'complete'

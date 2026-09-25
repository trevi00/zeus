"""The owner commands over the REAL primary store (storage-recovery-001, INV-FLEET-001).

`MemoryStore`'s reentrant lock hides the boundary that actually broke the first owner recovery:
`PostgresStore.transaction` opens its own connection and takes advisory lock 734219 for every
transaction, so the pre-fix observation callback - which `Fleet` calls again from inside its
committing transaction - waited on a lock the same call already held and failed with
`psycopg.errors.LockNotAvailable` when `lock_timeout` expired. These tests run the shipped
`zeus fleet reconcile-interrupted`, `zeus fleet relocate` and `zeus fleet migrate-host` entrypoints
against an actual isolated PostgreSQL schema (`isolated_pgstore`), so the first call, the commit and
the replay are measured on that store rather than on a substitute.

Scope of what is real here: the PRIMARY fleet store is PostgreSQL. The lane schema, the Docker
daemon and the machine call ledger are UNAVAILABLE in a test run and stay the labelled fixtures of
tests/test_fleet_recovery.py; the checkouts, journal and copied files of the relocation are real
files. The host migration's target lane schemas are REAL schemas created in the same disposable
database and checked by the shipped search-path rule. Without `HARNESS_INTEGRATION=1` and a
reachable database the fixture SKIPS: a skipped run is not evidence that any of this passed. Nothing
here touches a production schema, a registered fleet, a provider or a model, and no live recovery,
relocation or host migration is repeated.
"""
import json
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from test_fleet_host_migration import OLD_REPO, cli_migrate, cli_state, spy, stopped_journal
from test_fleet_host_migration import fault as observed_again
from test_fleet_host_migration import nested_observer as host_migration_observer
from test_fleet_recovery import (
    NestedStoreRead,
    NonReentrant,
    cli_reconcile,
    evidence,
    interrupted,
    nested_observer,
)
from test_fleet_relocation import cli_relocate, request_for
from test_fleet_relocation import nested_observer as relocation_observer
from test_fleet_relocation import setup as relocation_setup

from codex_harness.adapters import fleet_cli, fleet_recovery
from codex_harness.application.fleet import (
    BUCKET_HOST_MIGRATION,
    BUCKET_JOBS,
    BUCKET_RECOVERY,
    BUCKET_REGISTRY,
    BUCKET_RELOCATION,
    Fleet,
)
from codex_harness.bootstrap import database_url
from codex_harness.domain.fleet import FleetRefused, repository_identity
from codex_harness.domain.fleet_recovery import INTERRUPTED

pytestmark = pytest.mark.integration


def gone(*_, **__):
    """Injected fault: a committed operation must not observe any external state again."""
    raise AssertionError("a committed receipt must be answered without observing anything")


def test_the_reconcile_cli_first_call_commits_through_postgresql(tmp_path, monkeypatch, isolated_pgstore):
    """The exact failure that rolled back on 2026-09-22: the first call, over a real PostgreSQL
    store, commits one recovery receipt instead of timing out on advisory lock 734219."""
    setup = interrupted(tmp_path, store=isolated_pgstore)
    document = evidence(setup["job"], config_sha256=setup["config_sha256"])
    answer = cli_reconcile(setup, tmp_path, monkeypatch, store=isolated_pgstore, document=document)
    assert answer["exit_code"] == 0 and answer["cached"] is False
    assert answer["job"]["status"] == "failed" and answer["job"]["reason_code"] == INTERRUPTED
    with isolated_pgstore.transaction() as tx:
        receipt = tx.get(BUCKET_RECOVERY, document["job_id"])
        job = tx.get(BUCKET_JOBS, document["job_id"])
    assert receipt["id"] == answer["receipt"]["id"] and receipt["evidence"] == document
    assert job["owner_token"] is None and job["recovery"]["receipt_id"] == receipt["id"]
    # The identical CLI replay is answered from PostgreSQL alone; every external reader is a fault.
    for module, name in ((fleet_recovery, "collect_recovery_proof"), (fleet_recovery, "LaneReader"),
                         (fleet_recovery, "docker_state"), (fleet_recovery, "CallBudget")):
        monkeypatch.setattr(module, name, gone)

    def run(name, body):
        path = tmp_path / name
        path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
        return fleet_cli.execute(SimpleNamespace(store=isolated_pgstore),
                                 SimpleNamespace(fleet_command="reconcile-interrupted", file=path,
                                                 docker="docker"))

    replay = run("replay.json", document)
    assert replay["cached"] is True and replay["receipt"] == answer["receipt"]
    with pytest.raises(FleetRefused, match="recovery_conflict"):
        run("changed.json", {**document, "operator": "someone-else"})
    with isolated_pgstore.transaction() as tx:
        assert len(tx.scan(BUCKET_RECOVERY)) == 1


def test_the_relocate_cli_first_call_commits_through_postgresql(tmp_path, monkeypatch, isolated_pgstore):
    """The same boundary on the cutover command: the first call commits the migration receipt and the
    revised registry in one PostgreSQL transaction, and the identical replay reads no host state."""
    state = relocation_setup(tmp_path, store=isolated_pgstore)
    request = request_for(state)
    answer = cli_relocate(state, tmp_path, monkeypatch, store=isolated_pgstore, request=request)
    assert answer["exit_code"] == 0 and answer["relocated"] is True and answer["cached"] is False
    with isolated_pgstore.transaction() as tx:
        registry = tx.get(BUCKET_REGISTRY, "fleet-1")
        receipt = tx.get(BUCKET_RELOCATION, answer["receipt"]["id"])
        job = tx.get(BUCKET_JOBS, "op-1")
    assert registry["config_sha256"] == answer["config_sha256"] != state["config_sha256"]
    assert registry["config"]["lanes"][0]["repository"] == str(state["target"])
    assert registry["config"]["lanes"][0]["runtime"] == str(state["target_runtime"])
    assert registry["config"]["lanes"][0]["schema"] == "lane_a"
    assert receipt["prior_config_sha256"] == state["config_sha256"]
    assert job["repository"] == repository_identity(str(state["source"]))
    monkeypatch.setattr(fleet_recovery, "collect_relocation_proof", gone)
    replay = cli_relocate(state, tmp_path, monkeypatch, store=isolated_pgstore, request=request,
                          docker=gone, name="replay.json")
    assert replay["cached"] is True and replay["receipt"] == answer["receipt"]
    with pytest.raises(FleetRefused, match="relocation_conflict"):
        cli_relocate(state, tmp_path, monkeypatch, store=isolated_pgstore, docker=gone,
                     request=request_for(state, operator="someone-else"), name="other.json")
    with isolated_pgstore.transaction() as tx:
        assert len(tx.scan(BUCKET_RELOCATION)) == 1


def test_the_pre_fix_reconcile_observation_times_out_on_postgresql(tmp_path, isolated_pgstore):
    """The control that binds the deterministic `NonReentrant` regression to the real store: the
    pre-fix callback, which read the registry through the primary store inside the commit, fails here
    with `psycopg.errors.LockNotAvailable` - the error the owner's first recovery actually hit. This
    case deliberately waits out the nested transaction's `lock_timeout` (10s), and commits nothing."""
    setup = interrupted(tmp_path, store=isolated_pgstore)
    document = evidence(setup["job"], config_sha256=setup["config_sha256"])
    observe = nested_observer(isolated_pgstore, setup, tmp_path, document)
    with pytest.raises(psycopg.errors.LockNotAvailable):
        Fleet(isolated_pgstore).reconcile_interrupted(document, observe=observe, reread=observe)
    with isolated_pgstore.transaction() as tx:
        assert tx.scan(BUCKET_RECOVERY) == []
        assert tx.get(BUCKET_JOBS, document["job_id"])["status"] == "dispatching"


def test_the_pre_fix_relocate_observation_times_out_on_postgresql(tmp_path, isolated_pgstore):
    """The same pre-fix pattern on the cutover command, over the real store, beside the deterministic
    stand-in the unit regression uses: both refuse, and neither commits. Also waits out one 10s
    `lock_timeout`."""
    state = relocation_setup(tmp_path, store=isolated_pgstore)
    request = request_for(state)
    with pytest.raises(psycopg.errors.LockNotAvailable):
        Fleet(isolated_pgstore).relocate(request, observe=relocation_observer(state, isolated_pgstore, request),
                                         reread=relocation_observer(state, isolated_pgstore, request))
    wrapped = NonReentrant(isolated_pgstore)
    observe = relocation_observer(state, wrapped, request)
    with pytest.raises(NestedStoreRead):
        Fleet(wrapped).relocate(request, observe=observe, reread=observe)
    with isolated_pgstore.transaction() as tx:
        assert tx.scan(BUCKET_RELOCATION) == []
        assert tx.get(BUCKET_REGISTRY, "fleet-1")["config_sha256"] == state["config_sha256"]


@pytest.fixture
def target_schemas(isolated_pgstore):
    """Two provisioned target lane schemas in the disposable database, dropped afterwards."""
    names = {lane: "t" + uuid4().hex[:12] + "_" + lane for lane in ("harness", "interface")}
    with psycopg.connect(database_url()) as connection:
        for name in names.values():
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
            connection.execute(sql.SQL("CREATE TABLE {}.documents (id text)").format(sql.Identifier(name)))
    try:
        yield names
    finally:
        with psycopg.connect(database_url()) as connection:
            for name in names.values():
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def test_the_migrate_host_cli_first_call_commits_through_postgresql(tmp_path, monkeypatch, isolated_pgstore,
                                                                     target_schemas):
    """C3, the exact path that exited 1 with `LockNotAvailable`: the shipped command's observation
    callback is re-read inside `Fleet.migrate_host`'s commit. Over the real store it now commits, and
    the journal and the REAL target schemas are observed on both reads."""
    state = cli_state(tmp_path, isolated_pgstore, schemas=target_schemas)
    journals = spy(monkeypatch, "runner_state")
    schemas = spy(monkeypatch, "_schema_provisioned")
    answer = cli_migrate(state, tmp_path)
    assert answer["exit_code"] == 0 and answer["migrated"] is True and answer["cached"] is False
    assert len(journals) == 2 and sorted(call[1] for call in schemas) == sorted(2 * list(target_schemas.values()))
    with isolated_pgstore.transaction() as tx:
        registry = tx.get(BUCKET_REGISTRY, "zeus-local-fleet")
        receipt = tx.get(BUCKET_HOST_MIGRATION, answer["receipt"]["id"])
        job = tx.get(BUCKET_JOBS, "op-q")
    assert registry["config_sha256"] == receipt["config_sha256"] == answer["config_sha256"]
    assert {lane["id"]: lane["schema"] for lane in registry["config"]["lanes"]} == target_schemas
    assert {lane["id"]: lane["queued_bindings"] for lane in receipt["proof"]["lanes"]} == \
        {"harness": [{"job_id": "op-q", "base_present": True, "goal_matches": True}], "interface": []}
    assert job["status"] == "queued" and job["repository"] == repository_identity(OLD_REPO)  # frozen row kept
    # The identical replay is answered from PostgreSQL alone; every external reader is a fault.
    for name in ("collect_host_migration_proof", "runner_state", "docker_state", "_schema_provisioned"):
        monkeypatch.setattr(fleet_recovery, name, observed_again)
    state["journal"].unlink()
    replay = cli_migrate(state, tmp_path, name="replay.json")
    assert replay["cached"] is True and replay["receipt"] == answer["receipt"]
    with isolated_pgstore.transaction() as tx:
        assert len(tx.scan(BUCKET_HOST_MIGRATION)) == 1


def test_a_changed_journal_refuses_the_migrate_host_commit_on_postgresql(tmp_path, monkeypatch, isolated_pgstore,
                                                                        target_schemas):
    """External facts stay fresh: a service run between the two observations changes the proof binding,
    and the real commit refuses without writing a receipt or the registry."""
    state = cli_state(tmp_path, isolated_pgstore, schemas=target_schemas)
    spy(monkeypatch, "runner_state", before=lambda n: n == 2 and stopped_journal(state["journal"], "r2"))
    with pytest.raises(FleetRefused, match="proof_changed"):
        cli_migrate(state, tmp_path)
    with isolated_pgstore.transaction() as tx:
        assert tx.scan(BUCKET_HOST_MIGRATION) == []
        assert tx.get(BUCKET_REGISTRY, "zeus-local-fleet")["config_sha256"] == state["request"]["expected_config_sha256"]


def test_the_pre_fix_migrate_host_observation_times_out_on_postgresql(tmp_path, isolated_pgstore, target_schemas):
    """Control over the real store: the pre-fix callback's job scan inside the commit fails with
    `psycopg.errors.LockNotAvailable`, as the owner's migrate-host run did. Waits out one 10s
    `lock_timeout`, and commits nothing."""
    state = cli_state(tmp_path, isolated_pgstore, schemas=target_schemas)
    observe = host_migration_observer(state)
    with pytest.raises(psycopg.errors.LockNotAvailable):
        Fleet(isolated_pgstore).migrate_host(state["request"], observe=observe, reread=observe)
    with isolated_pgstore.transaction() as tx:
        assert tx.scan(BUCKET_HOST_MIGRATION) == []

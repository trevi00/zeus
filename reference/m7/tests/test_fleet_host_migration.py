"""Fleet host migration (INV-FLEET-001, INV-HOST-MIGRATION-001): the D2 registry rebinding.

Memory store and a fabricated TARGET-host observation only; the real observation and a real
PostgreSQL registry are exercised by tests/test_host_migration_pg_rehearsal.py when disposable
servers are named. The `zeus fleet migrate-host` adapter command is exercised at the end of this file
over real target files and Git, and over the real primary store in tests/test_fleet_recovery_postgres.py.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from codex_harness.adapters import fleet_cli, fleet_recovery
from codex_harness.adapters.fleet_recovery import checkout_identity, run_root
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import BUCKET_JOBS, BUCKET_REGISTRY, Fleet
from codex_harness.domain.fleet import (
    FleetRefused,
    config_digest,
    repository_identity,
    resolve_repository,
    validate_budget,
)
from codex_harness.domain.fleet_recovery import HOST_MIGRATION_PROOF_SCHEMA, HOST_MIGRATION_SCHEMA

OLD_REPO = "C:\\workspaces\\zeus\\worktrees\\fleet-001"
IDENTITY = "e" * 64
CONFIG = {"schema": "urn:zeus:fleet:1", "id": "zeus-local-fleet", "max_parallel": 2,
          "budget": validate_budget({"total": 160, "per_host": 160}),
          "lanes": [{"id": "harness", "team": "harness", "schema": "zeus_fleet_harness", "redis_namespace": "zeus-fleet-harness",
                     "repository": OLD_REPO, "runtime": "C:\\workspaces\\zeus\\artifacts\\f2h"},
                    {"id": "interface", "team": "interface", "schema": "zeus_fleet_interface",
                     "redis_namespace": "zeus-fleet-interface", "repository": OLD_REPO,
                     "runtime": "C:\\workspaces\\zeus\\artifacts\\f2i"}]}
CONFIG["lanes"] = [{k: lane[k] for k in sorted(lane)} for lane in CONFIG["lanes"]]
# D2: repository /srv/zeus/repo, runtimes per lane, the renamed schemas; ids/teams/namespaces kept.
# The TARGET side is the host's own native absolute path (the rebinding runs on the target host):
# /srv/zeus on aibox. On a Windows test host the same policy is exercised with a drive-rooted
# equivalent, so the rules run everywhere instead of being skipped there.
SRV = "/srv/zeus" if os.name != "nt" else "C:\\srv\\zeus"
REPO = os.path.join(SRV, "repo")
TARGETS = {"harness": (os.path.join(SRV, "runtime", "lanes", "harness"), "zeus_aibox_harness"),
           "interface": (os.path.join(SRV, "runtime", "lanes", "interface"), "zeus_aibox_interface")}


def store(paused=True, jobs=()):
    memory = MemoryStore()
    with memory.transaction() as tx:
        tx.put(BUCKET_REGISTRY, CONFIG["id"], {"id": CONFIG["id"], "schema": CONFIG["schema"], "config": CONFIG,
                                               "config_sha256": config_digest(CONFIG), "registered_at": "t0"})
        for job in jobs:
            tx.put(BUCKET_JOBS, job["id"], job)
    if paused:
        Fleet(memory).pause()
    return memory


def request(**overrides):
    document = {"schema": HOST_MIGRATION_SCHEMA, "fleet": CONFIG["id"], "operator": "owner",
                "migration_id": "aibox-migration-001", "manifest_sha256": "a" * 64,
                "expected_config_sha256": config_digest(CONFIG), "source_repository_identity": IDENTITY,
                "lanes": [{"lane": lane["id"], "repository": {"from": OLD_REPO, "to": REPO},
                           "runtime": {"from": lane["runtime"], "to": TARGETS[lane["id"]][0]},
                           "schema": {"from": lane["schema"], "to": TARGETS[lane["id"]][1]}}
                          for lane in CONFIG["lanes"]],
                "recorded_at": "2026-09-25T09:00:00Z"}
    document.update(overrides)
    return document


def proof(**lane_overrides):
    lanes = []
    for lane in ("harness", "interface"):
        row = {"id": lane, "active_runs": 0, "repository": {"target_identity": IDENTITY, "independent": True},
               "runtime": {"writable": True}, "schema": {"name": TARGETS[lane][1], "provisioned": True},
               "queued_bindings": []}
        row.update(lane_overrides.get(lane, {}))
        lanes.append(row)
    return {"schema": HOST_MIGRATION_PROOF_SCHEMA, "runner": {"state": "stopped"}, "lanes": lanes, "observed_at": "t1"}


def test_d2_rebinds_every_lane_keeps_identities_and_resolves_frozen_history():
    frozen = {"id": "job-1", "lane": "harness", "status": "accepted", "repository": repository_identity(OLD_REPO)}
    memory = store(jobs=[frozen])
    fleet = Fleet(memory)
    result = fleet.migrate_host(request(), proof())
    assert result["migrated"] and result["cached"] is False
    with memory.transaction() as tx:
        registry = tx.get(BUCKET_REGISTRY, CONFIG["id"])
        receipt = tx.scan("fleet_host_migrations")[0]
        job = tx.get(BUCKET_JOBS, "job-1")
        aliases = fleet._repository_aliases(tx)
    lanes = {lane["id"]: lane for lane in registry["config"]["lanes"]}
    assert {k: (v["repository"], v["runtime"], v["schema"]) for k, v in lanes.items()} == \
        {k: (REPO, *TARGETS[k]) for k in TARGETS}
    assert [(v["team"], v["redis_namespace"]) for v in lanes.values()] == \
        [("harness", "zeus-fleet-harness"), ("interface", "zeus-fleet-interface")]
    assert receipt["prior_config"] == CONFIG and receipt["prior_config_sha256"] == config_digest(CONFIG)
    assert registry["config_sha256"] == receipt["config_sha256"] != config_digest(CONFIG)
    assert job == frozen  # history keeps its original path identity
    assert resolve_repository(job["repository"], aliases) == repository_identity(REPO)
    assert fleet.migrate_host(request(), proof())["cached"] is True
    with pytest.raises(FleetRefused, match="host_migration_conflict"):
        fleet.migrate_host(request(recorded_at="2026-09-25T10:00:00Z"), proof())


@pytest.mark.parametrize("mutate, reason", [
    (lambda r: r.update(expected_config_sha256="0" * 64), "config_expected_mismatch"),
    (lambda r: r["lanes"].pop(), "host_migration_lanes_incomplete"),
    (lambda r: r["lanes"][0]["schema"].update(to="public"), "config_invalid"),
    (lambda r: r["lanes"][0]["runtime"].update(**{"from": "C:\\elsewhere"}), "source_binding_mismatch"),
    (lambda r: r["lanes"][0]["repository"].update(to="relative/repo"), "host_migration_invalid"),
    (lambda r: r["lanes"][1]["schema"].update(to="zeus_aibox_harness"), "config_duplicate"),
])
def test_invalid_requests_refuse_without_a_write(mutate, reason):
    memory = store()
    document = request()
    mutate(document)
    with pytest.raises(FleetRefused) as refused:
        Fleet(memory).migrate_host(document, proof())
    assert refused.value.reason_code == reason
    with memory.transaction() as tx:
        assert tx.get(BUCKET_REGISTRY, CONFIG["id"])["config"] == CONFIG
        assert tx.scan("fleet_host_migrations") == []


@pytest.mark.parametrize("lanes, reason", [
    ({"harness": {"repository": {"target_identity": "f" * 64, "independent": True}}}, "repository_identity_mismatch"),
    ({"harness": {"schema": {"name": "zeus_aibox_harness", "provisioned": False}}}, "target_schema_unprovisioned"),
    ({"interface": {"active_runs": 1}}, "lane_run_active"),
    ({"interface": {"runtime": {"writable": False}}}, "runtime_unwritable"),
])
def test_target_observation_failures_refuse(lanes, reason):
    with pytest.raises(FleetRefused) as refused:
        Fleet(store()).migrate_host(request(), proof(**lanes))
    assert refused.value.reason_code == reason


def test_unpaused_fleet_or_running_runner_refuses():
    with pytest.raises(FleetRefused, match="fleet_not_paused"):
        Fleet(store(paused=False)).migrate_host(request(), proof())
    running = proof()
    running["runner"] = {"state": "running"}
    with pytest.raises(FleetRefused, match="runner_not_stopped"):
        Fleet(store()).migrate_host(request(), running)
    queued = {"id": "job-q", "lane": "harness", "status": "queued", "repository": repository_identity(OLD_REPO)}
    with pytest.raises(FleetRefused, match="queued_binding_incomplete"):
        Fleet(store(jobs=[queued])).migrate_host(request(), proof())
    bound = proof(harness={"queued_bindings": [{"job_id": "job-q", "base_present": True, "goal_matches": True}]})
    assert Fleet(store(jobs=[queued])).migrate_host(request(), copy.deepcopy(bound))["migrated"]


# ----- the shipped `zeus fleet migrate-host` adapter command ---------------------------------
# The target checkout, runtimes and service journal below are REAL files and Git; Docker is never
# asked because every runs root is empty. The target-schema check is a labelled fixture here (no
# database in a unit run) and real in tests/test_fleet_recovery_postgres.py.


class NestedStoreRead(AssertionError):
    """Labelled stand-in for `psycopg.errors.LockNotAvailable` on advisory lock 734219."""


class NonReentrant:
    """Injected fault: the primary store's non-reentrant PostgreSQL boundary made visible over
    `MemoryStore` (whose RLock would accept a nested transaction silently)."""

    def __init__(self, store):
        self.store, self.depth = store, 0

    @contextmanager
    def transaction(self):
        if self.depth:
            raise NestedStoreRead("nested primary-store transaction while advisory lock 734219 is held")
        self.depth += 1
        try:
            with self.store.transaction() as tx:
                yield tx
        finally:
            self.depth -= 1


def git(repo, *argv):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=f@x", "-c", "user.name=f", *argv],
                          check=True, capture_output=True, text=True).stdout.strip()


def stopped_journal(path, run_id="r1"):
    path.write_text(json.dumps({"event": "start", "run_id": run_id}) + "\n"
                    + json.dumps({"event": "exit", "run_id": run_id}) + "\n", encoding="utf-8")


def cli_state(tmp_path, backing, *, schemas=None):
    """A restored registry on `backing` (paused, one queued job) and a real target host tree."""
    root = tmp_path / "srv"
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "docs").mkdir()
    (repo / "docs" / "goal.md").write_text("goal\n", encoding="utf-8")
    git(repo, "add", "docs/goal.md")
    git(repo, "commit", "-q", "-m", "root")
    head = git(repo, "rev-parse", "HEAD")
    runtimes = {lane: root / "runtime" / lane for lane in TARGETS}
    for path in runtimes.values():
        run_root(str(path)).mkdir(parents=True)  # initialized runtime: an empty runs root
    journal = root / "journal.jsonl"
    stopped_journal(journal)
    queued = {"id": "op-q", "lane": "harness", "status": "queued", "repository": repository_identity(OLD_REPO),
              "goal": {"base_revision": head, "path": "docs/goal.md",
                       "sha256": hashlib.sha256(b"goal\n").hexdigest()}}
    with backing.transaction() as tx:
        tx.put(BUCKET_REGISTRY, CONFIG["id"], {"id": CONFIG["id"], "schema": CONFIG["schema"], "config": CONFIG,
                                               "config_sha256": config_digest(CONFIG), "registered_at": "t0"})
        tx.put(BUCKET_JOBS, queued["id"], queued)
    Fleet(backing).pause()
    schemas = schemas or {lane: TARGETS[lane][1] for lane in TARGETS}
    document = request(source_repository_identity=checkout_identity(str(repo)))
    for move in document["lanes"]:
        move["repository"]["to"] = str(repo)
        move["runtime"]["to"] = str(runtimes[move["lane"]])
        move["schema"]["to"] = schemas[move["lane"]]
    return {"store": backing, "journal": journal, "request": document, "repo": repo}


def cli_migrate(state, tmp_path, *, store=None, name="request.json"):
    path = tmp_path / name
    path.write_text(json.dumps(state["request"], sort_keys=True), encoding="utf-8")
    return fleet_cli.execute(SimpleNamespace(store=state["store"] if store is None else store),
                             SimpleNamespace(fleet_command="migrate-host", file=path,
                                             journal=state["journal"], docker="docker"))


def spy(monkeypatch, name, before=None):
    """Counts calls to a REAL fleet_recovery reader; `before(n)` runs ahead of call n."""
    real, calls = getattr(fleet_recovery, name), []

    def wrapped(*args, **kwargs):
        calls.append(args)
        if before is not None:
            before(len(calls))
        return real(*args, **kwargs)

    monkeypatch.setattr(fleet_recovery, name, wrapped)
    return calls


def fault(*_, **__):
    """Injected fault: a committed migration must be answered without observing anything."""
    raise AssertionError("a committed receipt must be answered without observing anything")


def unit_schema_fixture(monkeypatch):
    """Labelled fixture for the target-schema check: no database exists in a unit run."""
    calls = []
    monkeypatch.setattr(fleet_recovery, "_schema_provisioned",
                        lambda dsn, schema, verify=None: calls.append(schema) or True)
    return calls


def test_the_migrate_host_cli_pins_only_jobs_and_observes_external_facts_twice(tmp_path, monkeypatch):
    """C3: the second observation runs inside the commit, so it must not open a primary-store
    transaction; the journal, checkout and schema facts are still read on both observations."""
    state = cli_state(tmp_path, NonReentrant(MemoryStore()))
    schemas = unit_schema_fixture(monkeypatch)
    journals = spy(monkeypatch, "runner_state")
    answer = cli_migrate(state, tmp_path)
    assert answer["exit_code"] == 0 and answer["migrated"] is True and answer["cached"] is False
    assert len(journals) == 2 and len(schemas) == 4
    with state["store"].transaction() as tx:
        receipt = tx.get("fleet_host_migrations", answer["receipt"]["id"])
    assert {lane["id"]: lane["queued_bindings"] for lane in receipt["proof"]["lanes"]} == \
        {"harness": [{"job_id": "op-q", "base_present": True, "goal_matches": True}], "interface": []}
    for name in ("collect_host_migration_proof", "runner_state", "docker_state", "_schema_provisioned"):
        monkeypatch.setattr(fleet_recovery, name, fault)
    state["journal"].unlink()
    replay = cli_migrate(state, tmp_path, name="replay.json")
    assert replay["cached"] is True and replay["receipt"] == answer["receipt"]


def test_the_pre_fix_migrate_host_observation_reads_the_store_inside_the_commit(tmp_path, monkeypatch):
    """Control: the pre-fix callback scanned jobs through the primary store on every observation."""
    state = cli_state(tmp_path, NonReentrant(MemoryStore()))
    unit_schema_fixture(monkeypatch)
    with pytest.raises(NestedStoreRead):
        Fleet(state["store"]).migrate_host(state["request"], observe=nested_observer(state),
                                           reread=nested_observer(state))
    with state["store"].transaction() as tx:
        assert tx.scan("fleet_host_migrations") == []


def nested_observer(state):
    """The PRE-FIX adapter callback (258336a): a primary-store job scan on every observation."""
    from codex_harness.adapters.configuration import settings

    def observe():
        with state["store"].transaction() as tx:
            jobs = tx.scan(BUCKET_JOBS)
        return fleet_recovery.collect_host_migration_proof(state["request"], jobs, journal=state["journal"],
                                                           host_dsn=settings().get("HARNESS_DATABASE_URL") or "",
                                                           state=fault)
    return observe


def test_a_journal_change_between_observations_refuses_without_commit(tmp_path, monkeypatch):
    state = cli_state(tmp_path, NonReentrant(MemoryStore()))
    unit_schema_fixture(monkeypatch)
    spy(monkeypatch, "runner_state", before=lambda n: n == 2 and stopped_journal(state["journal"], "r2"))
    with pytest.raises(FleetRefused, match="proof_changed"):
        cli_migrate(state, tmp_path)
    with state["store"].transaction() as tx:
        assert tx.scan("fleet_host_migrations") == []
        assert tx.get(BUCKET_REGISTRY, CONFIG["id"])["config_sha256"] == config_digest(CONFIG)


def test_a_job_queued_after_the_pinned_scan_refuses_on_the_commits_own_queued_set(tmp_path, monkeypatch):
    """The pinned job rows never become the denominator: the commit re-reads the queued set."""
    state = cli_state(tmp_path, NonReentrant(MemoryStore()))
    unit_schema_fixture(monkeypatch)
    real, observed = fleet_recovery.collect_host_migration_proof, []

    def first_then_enqueue(*args, **kwargs):
        proof = real(*args, **kwargs)
        observed.append(proof)
        if len(observed) == 1:  # after the first observation, before the commit's transaction opens
            with state["store"].transaction() as tx:
                tx.put(BUCKET_JOBS, "op-late", {**tx.get(BUCKET_JOBS, "op-q"), "id": "op-late"})
        return proof

    monkeypatch.setattr(fleet_recovery, "collect_host_migration_proof", first_then_enqueue)
    with pytest.raises(FleetRefused, match="queued_binding_incomplete"):
        cli_migrate(state, tmp_path)
    with state["store"].transaction() as tx:
        assert tx.scan("fleet_host_migrations") == []

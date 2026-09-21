"""Owner recovery of one interrupted fleet job (storage-recovery-001, INV-FLEET-001).

Every service this recovery reads across is UNAVAILABLE here, so each one is replaced by a
controlled, labelled fixture and every fault is injected on purpose: `LaneDouble` holds the exact
documents a lane PostgreSQL schema would hold, `ledger` holds machine call slots as the file ledger
writes them, and `stopped`/`running`/`unavailable` are Docker answers, not a Docker daemon. The
filesystem side (retained isolation run records) is real files under `tmp_path`. No provider, no
container, no PostgreSQL and no model is reached by anything in this file.
"""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from codex_harness.adapters.fleet_recovery import collect_recovery_proof, run_root
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import BUCKET_JOBS, BUCKET_RECOVERY, Fleet
from codex_harness.domain.fleet import FleetRefused
from codex_harness.domain.fleet_recovery import (
    EVIDENCE_SCHEMA,
    INTERRUPTED,
    validate_recovery_evidence,
)
from codex_harness.domain.operation import validate_manifest

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
TASK = "task-92b13b20"
OPERATION = "op-1"
CORRELATION = "operation:" + OPERATION
RUN = "1a" * 16
CONTAINER = "c7" * 32
RESERVATION = "d4" * 32
SLOT = "e9" * 16
PAST = "2026-09-20T00:00:00+00:00"
NOW = "2026-09-21T00:00:00+00:00"


def config(tmp_path, **overrides):
    lanes = [{"id": "a", "team": "alpha", "repository": str(tmp_path / "repo-a"), "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": str(tmp_path / "rt-a")},
             {"id": "b", "team": "beta", "repository": str(tmp_path / "repo-b"), "schema": "lane_b",
              "redis_namespace": "fleet-b", "runtime": str(tmp_path / "rt-b")}]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
            "budget": {"per_host": 4, "total": 8}, "lanes": lanes, **overrides}


def manifest(op_id, paths):
    return validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + op_id, "rationale": CANARY},
        "plan": {"objective": CANARY, "acceptance_criteria": ["ok"], "allowed_paths": paths},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}},
        packaged_policy())


GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}


class LaneDouble:
    """The lane schema's `documents` rows, exactly as workflow, executor and the invocation ledger
    write them. A controlled fixture: no PostgreSQL connection exists in this test run."""

    def __init__(self, documents):
        self.documents = documents

    def get(self, bucket, key):
        return deepcopy(self.documents.get(bucket, {}).get(key))

    def scan(self, bucket):
        return [deepcopy(row) for _, row in sorted(self.documents.get(bucket, {}).items())]


class Ledger:
    """The machine call budget as the file ledger reads back. Reserving here is a test failure:
    recovery never takes a call slot."""

    def __init__(self, rows):
        self.rows = rows

    def slots(self):
        return [dict(row) for row in self.rows]

    def reserve(self, **_):  # pragma: no cover - the assertion is the point
        raise AssertionError("owner recovery must never reserve a provider call slot")


def lane_documents(**overrides):
    documents = {
        "operations": {OPERATION: {"id": OPERATION, "correlation_id": CORRELATION, "cycle_id": CORRELATION,
                                   "assignment_message_id": "msg-1", "status": "running"}},
        "tasks": {TASK: {"id": TASK, "status": "cancelled", "generation": 2, "attempt": 1,
                         "lease_owner": None, "lease_until": PAST,
                         "message": {"correlation_id": CORRELATION}}},
        "execution_progress": {TASK: {"id": TASK, "worktree": "WORKTREE", "generation": 1, "attempt": 1}},
        "invocation_reservations": {RESERVATION: {"id": RESERVATION, "task_id": TASK, "bucket": "tasks",
                                                  "generation": 1, "attempt": 1, "status": "unsettled_unknown",
                                                  "usage": {"source": "unknown", "total_tokens": None}}},
    }
    for bucket, rows in overrides.items():
        documents[bucket] = rows
    return documents


def worktree_of(tmp_path):
    return str(tmp_path / "worktree")


def lane_store(tmp_path, **overrides):
    documents = lane_documents(**overrides)
    if "execution_progress" not in overrides and documents["execution_progress"].get(TASK):
        documents["execution_progress"][TASK]["worktree"] = worktree_of(tmp_path)
    return LaneDouble(documents)


def write_run_record(tmp_path, lane_runtime, **overrides):
    record = {"run_id": RUN, "role": "worker", "workspace": worktree_of(tmp_path),
              "container": CONTAINER, "container_name": "zeus-worker-" + RUN,
              "image": "sha256:" + "f" * 64, "label": "zeus.isolated.run=" + RUN,
              "state": "stop_unconfirmed", "lifecycle": [], **overrides}
    directory = run_root(lane_runtime) / record["run_id"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "run.json").write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    return record


def evidence(job, **overrides):
    document = {"schema": EVIDENCE_SCHEMA, "job_id": job["id"], "operator": "owner",
                "expected": {"status": job["status"], "owner_token": job["owner_token"],
                             "lane": job["lane"], "config_sha256": overrides.pop("config_sha256")},
                "lane_operation": {"id": OPERATION, "correlation_id": CORRELATION, "task_id": TASK,
                                   "generation": 2},
                "container": {"run_id": RUN, "role": "worker", "name": "zeus-worker-" + RUN, "id": CONTAINER},
                "invocation": {"reservation_id": RESERVATION, "status": "unsettled_unknown"},
                "machine_slot": {"id": SLOT, "outcome": "interrupted_unknown"},
                "recorded_at": NOW}
    for key, value in overrides.items():
        document[key] = {**document[key], **value} if isinstance(value, dict) and key in document else value
    return document


def stopped(_container_id):
    return {"status": "exited", "exit_code": 255}


def running(_container_id):
    return {"status": "running", "exit_code": None}


def unavailable(_container_id):
    """Injected fault: the Docker daemon could not answer about this exact id."""
    return None


def ledger(**overrides):
    return Ledger([{"id": SLOT, "host": "h", "status": "used", "purpose": "operation",
                    "outcome": "interrupted_unknown", **overrides}])


def interrupted(tmp_path, status="dispatching", *, second=False):
    store = MemoryStore()
    fleet = Fleet(store)
    registry = fleet.register(config(tmp_path))
    fleet.enqueue("a", manifest(OPERATION, ["docs/x.md"]), GOAL, [])
    if second:
        fleet.enqueue("a", manifest("op-2", ["docs/x.md"]), GOAL, [])
    job = fleet.admit_one()["job"]
    if status == "unknown":
        fleet.finalize(job["id"], job["owner_token"], {"status": "unknown", "reason_code": "spawn_uncertain",
                                                       "exit_code": None, "calls": {"reserved": 1, "settled": None}})
    fleet.pause()
    with store.transaction() as tx:
        job = tx.get(BUCKET_JOBS, job["id"])
    lane = [lane for lane in config(tmp_path)["lanes"] if lane["id"] == "a"][0]
    write_run_record(tmp_path, lane["runtime"])
    return {"store": store, "fleet": fleet, "job": job, "lane": lane,
            "config_sha256": registry["config_sha256"]}


def proof_for(setup, tmp_path, *, documents=None, state=stopped, slots=None, document=None):
    reader = documents if documents is not None else lane_store(tmp_path)
    return collect_recovery_proof(document or evidence(setup["job"], config_sha256=setup["config_sha256"]),
                                  setup["lane"], reader=reader, budget=slots or ledger(), state=state,
                                  clock=lambda: NOW)


# ----- the evidence document ---------------------------------------------------------------
def test_evidence_document_is_strict_and_never_echoes_values(tmp_path):
    setup = interrupted(tmp_path)
    good = evidence(setup["job"], config_sha256=setup["config_sha256"])
    assert validate_recovery_evidence(good) == good
    bad = [
        {"schema": "urn:zeus:fleet-recovery-evidence:2"}, {"job_id": "bad id"}, {"operator": ""},
        {"expected": {"status": "queued"}}, {"expected": {"status": "accepted"}},
        {"expected": {"owner_token": "short"}}, {"expected": {"config_sha256": "x" * 64}},
        {"lane_operation": {"correlation_id": "operation:other"}},
        {"lane_operation": {"generation": 0}}, {"lane_operation": {"generation": True}},
        {"container": {"name": "zeus-worker-other"}}, {"container": {"id": "z" * 64}},
        {"container": {"run_id": RUN.upper()}},
        {"invocation": {"status": "reserved"}}, {"invocation": {"reservation_id": "0" * 63}},
        {"machine_slot": {"outcome": "not a token: " + CANARY}}, {"machine_slot": {"id": SLOT + "00"}},
        {"recorded_at": "2026-09-21T00:00:00"},
        {"recorded_at": None},
    ]
    for override in bad:
        with pytest.raises(FleetRefused) as info:
            validate_recovery_evidence(evidence(setup["job"], config_sha256=setup["config_sha256"], **override))
        assert CANARY not in str(info.value) and str(tmp_path) not in str(info.value)
    with pytest.raises(FleetRefused, match="recovery_invalid_fields"):
        validate_recovery_evidence({**good, "extra": 1})
    with pytest.raises(FleetRefused, match="recovery_schema"):
        validate_recovery_evidence("not a document")


# ----- the cross-store observation ----------------------------------------------------------
def test_proof_reads_every_store_and_preserves_unknown_usage(tmp_path):
    setup = interrupted(tmp_path)
    proof = proof_for(setup, tmp_path)
    assert proof["task"] == {"id": TASK, "status": "cancelled", "generation": 2, "lease_live": False}
    assert proof["container"]["state"] == "exited" and proof["container"]["exit_code"] == 255
    assert proof["container"]["bound_worktree"] is True
    assert proof["invocation"] == {"reservation_id": RESERVATION, "status": "unsettled_unknown",
                                   "usage_source": "unknown", "total_tokens": None}
    assert proof["machine_slot"] == {"id": SLOT, "status": "used", "outcome": "interrupted_unknown"}


@pytest.mark.parametrize("case,reason", [
    ("live_container", "container_not_stopped"),
    ("docker_unavailable", "docker_unavailable"),
    ("task_running", "task_not_cancelled"),
    ("task_generation", "task_generation_mismatch"),
    ("lease_live", "task_lease_live"),
    ("lease_unparsable", "task_lease_unknown"),
    ("foreign_task", "task_not_bound"),
    ("missing_task", "task_unknown"),
    ("unbound_operation", "lane_operation_unbound"),
    ("no_worktree", "container_binding_missing"),
    ("ambiguous_runs", "container_ambiguous"),
    ("other_container", "container_binding_mismatch"),
    ("open_reservation", "invocation_open"),
    ("second_open_reservation", "invocation_open"),
    ("missing_slot", "machine_slot_unknown"),
    ("unreadable_slot", "machine_slot_unreadable"),
    ("open_slot", "machine_slot_open"),
])
def test_missing_unreadable_or_live_proof_refuses(tmp_path, case, reason):
    setup = interrupted(tmp_path)
    documents, state, slots, document = lane_store(tmp_path), stopped, ledger(), None
    if case == "live_container":
        state = running
    elif case == "docker_unavailable":
        state = unavailable
    elif case == "task_running":
        documents.documents["tasks"][TASK].update(status="running", lease_until=PAST)
    elif case == "task_generation":
        documents.documents["tasks"][TASK]["generation"] = 3
    elif case == "lease_live":
        documents.documents["tasks"][TASK]["lease_until"] = "2099-01-01T00:00:00+00:00"
    elif case == "lease_unparsable":
        documents.documents["tasks"][TASK]["lease_until"] = "not-a-time"
    elif case == "foreign_task":
        documents.documents["tasks"][TASK]["message"] = {"correlation_id": "operation:other"}
    elif case == "missing_task":
        documents.documents["tasks"] = {}
    elif case == "unbound_operation":
        documents.documents["operations"][OPERATION]["cycle_id"] = "operation:other"
    elif case == "no_worktree":
        documents.documents["execution_progress"] = {}
    elif case == "ambiguous_runs":
        write_run_record(tmp_path, setup["lane"]["runtime"], run_id="9b" * 16,
                         container_name="zeus-worker-" + "9b" * 16)
    elif case == "other_container":
        write_run_record(tmp_path, setup["lane"]["runtime"], container="a" * 64)
    elif case == "open_reservation":
        documents.documents["invocation_reservations"][RESERVATION]["status"] = "reserved"
    elif case == "second_open_reservation":
        documents.documents["invocation_reservations"]["b" * 64] = {
            "id": "b" * 64, "task_id": TASK, "status": "reserved", "usage": {"source": "unknown"}}
    elif case == "missing_slot":
        slots = Ledger([])
    elif case == "unreadable_slot":
        slots = ledger(unreadable="ValueError")
    elif case == "open_slot":
        slots = ledger(status="reserved", outcome="interrupted_unknown")
    if case == "open_slot":
        # A reserved slot passes the adapter (it exists and is readable) and is refused by the
        # policy gate, which is what the application actually commits behind.
        proof = proof_for(setup, tmp_path, documents=documents, state=state, slots=slots)
        with pytest.raises(FleetRefused, match=reason) as info:
            setup["fleet"].reconcile_interrupted(evidence(setup["job"], config_sha256=setup["config_sha256"]), proof)
    else:
        with pytest.raises(FleetRefused, match=reason) as info:
            proof_for(setup, tmp_path, documents=documents, state=state, slots=slots, document=document)
    assert CANARY not in str(info.value) and str(tmp_path) not in str(info.value)


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Connection:
    """A lane connection stand-in: it answers `current_schema()` and one document query."""

    def __init__(self, schema, rows):
        self.schema, self.rows = schema, rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, parameters=None):
        return Rows([(self.schema,)]) if "current_schema" in statement else Rows(self.rows)


def test_an_unavailable_or_wrong_lane_source_is_a_refusal_not_an_absence():
    from codex_harness.adapters.fleet_recovery import LaneReader

    body = {"id": TASK, "status": "cancelled"}
    reader = LaneReader("dsn", "lane_a", connect=lambda *_, **__: Connection("lane_a", [(body,)]))
    assert reader.get("tasks", TASK) == body and reader.scan("tasks") == [body]
    assert LaneReader("dsn", "lane_a", connect=lambda *_, **__: Connection("lane_a", [])).get("tasks", TASK) is None
    wrong = LaneReader("dsn", "lane_a", connect=lambda *_, **__: Connection("public", [(body,)]))
    with pytest.raises(FleetRefused, match="lane_schema_mismatch"):
        wrong.get("tasks", TASK)

    def refused(*_, **__):
        """Injected fault: the lane database could not be reached at all."""
        raise OSError("connection refused")

    with pytest.raises(FleetRefused, match="lane_unreadable") as info:
        LaneReader("dsn", "lane_a", connect=refused).get("tasks", TASK)
    assert "connection refused" not in str(info.value) and "dsn" not in str(info.value)


def test_container_name_without_a_recorded_binding_is_not_proof(tmp_path):
    setup = interrupted(tmp_path)
    documents = lane_store(tmp_path)
    documents.documents["execution_progress"][TASK]["worktree"] = str(tmp_path / "somewhere-else")
    with pytest.raises(FleetRefused, match="container_binding_missing"):
        proof_for(setup, tmp_path, documents=documents)


# ----- the committing transaction -------------------------------------------------------------
def test_reconcile_settles_one_reservation_and_preserves_the_history(tmp_path):
    setup = interrupted(tmp_path, "unknown", second=True)
    fleet, document = setup["fleet"], evidence(setup["job"], config_sha256=setup["config_sha256"])
    before = setup["job"]
    answer = fleet.reconcile_interrupted(document, proof_for(setup, tmp_path, document=document))
    assert answer["cached"] is False
    assert answer["job"]["status"] == "failed" and answer["job"]["reason_code"] == INTERRUPTED
    assert answer["receipt"]["outcome"] == {"status": "failed", "reason_code": INTERRUPTED,
                                            "calls": "preserved_as_recorded", "usage": "unknown"}
    with setup["store"].transaction() as tx:
        after = tx.get(BUCKET_JOBS, before["id"])
        receipt = tx.get(BUCKET_RECOVERY, before["id"])
    assert after["calls"] == before["calls"] and after["manifest"] == before["manifest"]
    assert after["goal"] == before["goal"] and after["dependencies"] == before["dependencies"]
    assert after["exit_code"] == before["exit_code"] and after["owner_token"] is None
    assert receipt["evidence"] == document and receipt["proof"]["container"]["state"] == "exited"
    assert "not a distributed atomic transaction" in receipt["authority"]
    assert fleet.reconciliation_required() == []
    # The lane is free again, but nothing is admitted while the fleet stays paused.
    assert fleet.admit_one()["job"] is None and fleet.admit_one()["blocked"] == {"op-2": "paused"}
    fleet.resume()
    assert fleet.admit_one()["job"]["id"] == "op-2"


def test_identical_replay_is_idempotent_and_changed_evidence_conflicts(tmp_path):
    setup = interrupted(tmp_path)
    fleet, document = setup["fleet"], evidence(setup["job"], config_sha256=setup["config_sha256"])
    proof = proof_for(setup, tmp_path, document=document)
    first = fleet.reconcile_interrupted(document, proof)
    replay = fleet.reconcile_interrupted(document, proof)
    assert replay["cached"] is True and replay["receipt"] == first["receipt"]
    assert replay["job"]["status"] == "failed"
    with setup["store"].transaction() as tx:
        rows = tx.scan(BUCKET_RECOVERY)
    assert len(rows) == 1
    restarted = Fleet(setup["store"])  # a later process, reading the durable receipt only
    assert restarted.reconcile_interrupted(document, proof)["cached"] is True
    changed = {**document, "operator": "someone-else"}
    with pytest.raises(FleetRefused, match="recovery_conflict"):
        fleet.reconcile_interrupted(changed, proof_for(setup, tmp_path, document=changed))
    with setup["store"].transaction() as tx:
        assert tx.scan(BUCKET_RECOVERY) == rows


def test_a_concurrent_second_owner_finds_the_reservation_already_settled(tmp_path):
    setup = interrupted(tmp_path)
    document = evidence(setup["job"], config_sha256=setup["config_sha256"])
    proof = proof_for(setup, tmp_path, document=document)
    setup["fleet"].reconcile_interrupted(document, proof)
    other = Fleet(setup["store"])  # a second owner process against the same store
    stale = {**document, "expected": {**document["expected"], "owner_token": "f" * 32}}
    with pytest.raises(FleetRefused, match="recovery_conflict"):
        other.reconcile_interrupted(stale, proof)


@pytest.mark.parametrize("case,reason", [
    ("resumed", "fleet_not_paused"),
    ("stale_config", "config_expected_mismatch"),
    ("wrong_owner", "owner_mismatch"),
    ("wrong_status", "job_not_interrupted"),
    ("wrong_lane", "lane_mismatch"),
    ("unknown_job", "job_unknown"),
    ("wrong_operation", "operation_mismatch"),
])
def test_the_transaction_refuses_anything_it_was_not_shown(tmp_path, case, reason):
    setup = interrupted(tmp_path, second=True)
    fleet, job = setup["fleet"], setup["job"]
    document = evidence(job, config_sha256=setup["config_sha256"])
    proof = proof_for(setup, tmp_path, document=document)
    if case == "resumed":
        fleet.resume()
    elif case == "stale_config":
        document = {**document, "expected": {**document["expected"], "config_sha256": "0" * 64}}
    elif case == "wrong_owner":
        document = {**document, "expected": {**document["expected"], "owner_token": "1" * 32}}
    elif case == "wrong_status":
        document = {**document, "job_id": "op-2", "expected": {**document["expected"], "status": "unknown"}}
    elif case == "wrong_lane":
        document = {**document, "expected": {**document["expected"], "lane": "b"}}
    elif case == "unknown_job":
        document = {**document, "job_id": "op-absent"}
    elif case == "wrong_operation":
        document = {**document, "lane_operation": {**document["lane_operation"], "id": "op-2",
                                                   "correlation_id": "operation:op-2"}}
        proof = {**proof, "lane_operation": {**proof["lane_operation"], "id": "op-2",
                                             "correlation_id": "operation:op-2"}}
    with pytest.raises(FleetRefused, match=reason) as info:
        fleet.reconcile_interrupted(document, proof)
    assert CANARY not in str(info.value) and str(tmp_path) not in str(info.value)
    with setup["store"].transaction() as tx:
        assert tx.scan(BUCKET_RECOVERY) == []
        assert tx.get(BUCKET_JOBS, job["id"])["status"] == "dispatching"


def test_proof_that_changed_between_the_reads_refuses_before_commit(tmp_path):
    setup = interrupted(tmp_path)
    document = evidence(setup["job"], config_sha256=setup["config_sha256"])
    stale = proof_for(setup, tmp_path, document=document)
    # The re-read inside the transaction sees the same container running again.
    with pytest.raises(FleetRefused, match="container_not_stopped"):
        setup["fleet"].reconcile_interrupted(document, stale,
                                             reread=lambda: proof_for(setup, tmp_path, document=document,
                                                                      state=running))
    live = {**stale, "invocation": {**stale["invocation"], "status": "settled"}}
    with pytest.raises(FleetRefused, match="proof_mismatch"):
        setup["fleet"].reconcile_interrupted(document, stale, reread=lambda: live)
    moved = {**stale, "worktree_digest": "0" * 64}
    with pytest.raises(FleetRefused, match="proof_changed"):
        setup["fleet"].reconcile_interrupted(document, stale, reread=lambda: moved)
    with setup["store"].transaction() as tx:
        assert tx.scan(BUCKET_RECOVERY) == []


def test_a_proof_from_another_observation_is_refused(tmp_path):
    setup = interrupted(tmp_path)
    document = evidence(setup["job"], config_sha256=setup["config_sha256"])
    proof = proof_for(setup, tmp_path, document=document)
    for broken in ({**proof, "schema": "urn:zeus:other:1"},
                   {**proof, "task": {**proof["task"], "id": "task-other"}},
                   {**proof, "container": {**proof["container"], "bound_worktree": False}},
                   {**proof, "machine_slot": {**proof["machine_slot"], "id": "0" * 32}}):
        with pytest.raises(FleetRefused):
            setup["fleet"].reconcile_interrupted(document, broken)


def test_the_owner_command_exists_on_the_cli_and_carries_only_codes(tmp_path):
    from codex_harness.adapters.fleet_cli import refusal
    from codex_harness.cli import parser

    args = parser().parse_args(["fleet", "reconcile-interrupted", "--file", str(tmp_path / "evidence.json")])
    assert args.fleet_command == "reconcile-interrupted" and args.docker == "docker"
    printed = refusal(FleetRefused("container_not_stopped", "container.state"))
    assert printed == {"status": "refused", "reason_code": "container_not_stopped",
                       "error_type": "FleetRefused", "exit_code": 1}


def test_recovery_reads_no_repository_and_reserves_no_call(tmp_path):
    setup = interrupted(tmp_path)
    document = evidence(setup["job"], config_sha256=setup["config_sha256"])
    answer = setup["fleet"].reconcile_interrupted(document, proof_for(setup, tmp_path, document=document))
    text = json.dumps(answer, sort_keys=True)
    assert str(tmp_path) not in text and CANARY not in text and "lane_a" not in text
    assert setup["fleet"].recovery(document["job_id"])["id"] == answer["receipt"]["id"]
    assert setup["fleet"].recovery("op-absent") is None
    assert not list(Path(tmp_path).glob("**/slots"))

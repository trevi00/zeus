"""INV-COUNCIL-001 with labelled fixtures: the executor, budget, artifact store, snapshot port, clock
and every role output below are fault injection, never Claude, Codex, a DBA or a live council."""
import json
import traceback

import pytest
from test_autonomous import (
    BASE,
    CANARY,
    RESEARCH,
    ROLE_OUTPUTS,
    Artifacts,
    Clock,
    FakeExecutor,
    evidence_ref_of,
)
from test_autonomous import manifest as v1_manifest
from test_operation import BOUND_GOAL, IDENTITY, Bus, Collector, FakeBudget

from codex_harness.adapters.council_snapshot import ReadOnlySnapshot, SnapshotUnavailable
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.autonomous import AutonomousRefused, AutonomousRun
from codex_harness.application.council import CouncilRun
from codex_harness.application.local_cycle import EXECUTION_STATUSES
from codex_harness.application.operation import TERMINAL as OPERATION_TERMINAL
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.autonomous import (
    STAGES,
    AutonomousManifestError,
    validate_autonomous_manifest,
)
from codex_harness.domain.council import (
    OPERATION_STATUSES,
    RUN_STAGES,
    SCHEMA_AUTONOMOUS_V2,
    STAGES_V2,
    TASK_STATUSES,
    SnapshotError,
    check_snapshot,
    council_output,
    profile,
    report_from_dba,
    snapshot_digest,
    snapshot_envelope,
    snapshot_records,
    validate_any_manifest,
    validate_council_manifest,
    validate_current_state,
    validate_snapshot,
)
from codex_harness.domain.model import ContractError, canonical, digest, envelope

SECRET = "SECRET-row-text-never-emitted"
CURRENT_STATE = {"records": [{"bucket": "tasks", "id": "task-known"}, {"bucket": "operations", "id": "op-missing"},
                             {"bucket": "autonomous_runs", "id": "run-odd"}], "max_age_seconds": 600}
DB_ROWS = {("tasks", "task-known"): {"id": "task-known", "status": "succeeded", "agent": "worker:implementation", "error": SECRET},
           ("autonomous_runs", "run-odd"): {"id": "run-odd", "status": "running", "stage": "not a token!"}}
ORDER = ["lead:researcher", "lead:dba", "lead:research", "lead:improvement", "conductor", "worker:implementation", "lead:improvement"]


def manifest(**overrides):
    document = {**v1_manifest(), "schema": SCHEMA_AUTONOMOUS_V2, "id": "council-001", "current_state": json.loads(canonical(CURRENT_STATE))}
    document.update(overrides)
    return document


def valid(**overrides):
    return validate_council_manifest(manifest(**overrides), packaged_policy())


class FakeConnection:
    """psycopg-shaped connection double (fixture): records statements, serves the fixed rows."""

    def __init__(self, rows, log, fail_at=None):
        self.rows, self.log, self.fail_at = rows, log, fail_at

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        self.log.append(statement)
        if self.fail_at is not None and self.fail_at in statement:
            raise OSError("connection reset " + SECRET)
        if statement.startswith("SELECT current_database"):
            return _Cursor([("zeus", "test_schema", "18.0")])
        if statement.startswith("SELECT s.bucket"):
            buckets, ids = params
            return _Cursor([(b, i, self.rows[(b, i)]) for b, i in zip(buckets, ids) if (b, i) in self.rows])
        return _Cursor([])


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeSnapshotPort:
    """Wraps ReadOnlySnapshot around the fake connection; `mode` injects unavailable/malformed."""

    def __init__(self, clock, mode="ok", rows=None):
        self.clock, self.mode, self.calls, self.statements = clock, mode, 0, []
        self.rows = DB_ROWS if rows is None else rows

    def observe(self, selection, **binding):
        self.calls += 1
        if self.mode == "unavailable":
            raise SnapshotUnavailable("snapshot_unavailable")
        if self.mode == "malformed":
            return {"records": [{"body": SECRET}]}
        def connect(dsn, **kw):
            if self.mode == "connect_error":
                raise OSError("could not connect to " + dsn)  # a driver error quoting the DSN (injected fault)
            return FakeConnection(self.rows, self.statements, fail_at="unnest" if self.mode == "read_error" else None)
        return ReadOnlySnapshot("postgresql://user:" + SECRET + "@host/db", connect=connect, clock=self.clock).observe(selection, **binding)


class SnapshotArtifacts:
    """FileArtifacts-shaped put(body, source) over the test Artifacts store (fixture)."""

    def __init__(self, artifacts):
        self.artifacts = artifacts

    def put(self, body, source):
        return {"ref": self.artifacts.put(body), "source": source}


DBA_REPORT = {"summary": "task-known succeeded; op-missing absent at snapshot; run-odd unknown", "claim_ids": ["c1"],
              "unknowns": ["run-odd stage is not interpretable"]}
IMPROVEMENT = {"summary": "reuse the runbook path", "decision": "improve", "rationale": "extend rather than fork",
               "transition": {"compatibility": "additive", "rollback": "revert", "retirement": "none"}, "claim_ids": ["c1"],
               "findings": ROLE_OUTPUTS["attacker"]["findings"]}


class CouncilExecutor(FakeExecutor):
    """FakeExecutor plus: council roles fill in the identities they were given and every lead role
    files its `task.result` to its parent through the outbox, as `Workflow.complete` does (fixture).
    `swap_report` makes the improvement lead name a foreign report digest."""

    def __init__(self, svc, artifacts, swap_report=False, foreign_dba=False, **kwargs):
        super().__init__(svc, artifacts, **kwargs)
        self.swap_report, self.foreign_dba = swap_report, foreign_dba

    def execute_one(self, agent, expected=None):
        with self.svc.store.transaction() as tx:
            details = tx.get("tasks", expected["id"])["message"]["what"]["details"]
        role = details["role"] if agent != "worker:implementation" else None
        if role == "dba":
            self.outputs["dba"] = {"snapshot_digest": "0" * 64 if self.foreign_dba else details["snapshot_digest"], **DBA_REPORT}
        elif role in {"research_lead", "improvement_lead", "conductor"}:
            identities = {"snapshot_digest": details["snapshot_digest"], "report_digest": details["report_digest"]}
            if role == "improvement_lead" and self.swap_report:
                identities["report_digest"] = "f" * 64
            base = {"research_lead": ROLE_OUTPUTS["proposer"], "improvement_lead": IMPROVEMENT, "conductor": ROLE_OUTPUTS["arbiter"]}[role]
            self.outputs[role] = {**self.outputs.get(role, base), **identities}
        task = super().execute_one(agent, expected)
        if role is not None and task["status"] == "succeeded":
            with self.svc.store.transaction() as tx:
                report = envelope("task.result", task["agent"], task["message"]["who"]["sender"], "dge_role",
                                  {"task_id": task["id"], "result": task["result"]}, task["message"]["correlation_id"], task["id"])
                tx.put("outbox", report["message_id"], {"message": report, "sent": False})
        return task


def build(clock=None, snapshot_mode="ok", **kwargs):
    svc = Harness(MemoryStore(), organization())
    artifacts, clock = Artifacts(), clock or Clock()
    executor = CouncilExecutor(svc, artifacts, clock=clock, **kwargs)
    budget, port = FakeBudget(), FakeSnapshotPort(clock, snapshot_mode)
    run = CouncilRun(svc, executor, Bus(), Workflow(svc.store, svc.org), budget, Collector(),
                     verify_sources=lambda packet: [{**s, "bytes": 1} for s in packet["sources"]], repository="r",
                     clock=clock, evidence=artifacts, snapshot=port, artifacts=SnapshotArtifacts(artifacts))
    return svc, run, executor, budget, port


# ----- input --------------------------------------------------------------------------------------
def test_v2_manifest_keeps_the_v1_canonical_form_and_refuses_bad_current_state_before_any_provider():
    bound = valid()
    assert {k: bound[k] for k in bound if k not in {"schema", "current_state"}} == \
        {k: v for k, v in validate_autonomous_manifest(v1_manifest(id="council-001"), packaged_policy()).items() if k != "schema"}
    assert bound["current_state"] == CURRENT_STATE and profile(bound)["max_starts"] == 7 and profile(valid())["version"] == 2
    assert profile(validate_autonomous_manifest(v1_manifest(), packaged_policy())) == profile(validate_autonomous_manifest(v1_manifest(), packaged_policy()))
    assert profile(validate_autonomous_manifest(v1_manifest(), packaged_policy()))["max_starts"] == 6
    many = [{"bucket": "tasks", "id": "t" + str(i)} for i in range(21)]
    for change in ({"records": [], "max_age_seconds": 600}, {"records": many, "max_age_seconds": 600},
                   {"records": [{"bucket": "tasks", "id": "a"}, {"bucket": "tasks", "id": "a"}], "max_age_seconds": 600},
                   {"records": [{"bucket": "outbox", "id": "a"}], "max_age_seconds": 600},
                   {"records": [{"bucket": "tasks", "id": "../a"}], "max_age_seconds": 600},
                   {"records": [{"bucket": "tasks", "id": "a", "body": 1}], "max_age_seconds": 600},
                   {"records": [{"bucket": "tasks", "id": "a"}], "max_age_seconds": True},
                   {"records": [{"bucket": "tasks", "id": "a"}], "max_age_seconds": 59},
                   {"records": [{"bucket": "tasks", "id": "a"}], "max_age_seconds": 3601},
                   {"records": [{"bucket": "tasks", "id": "a"}], "max_age_seconds": "600"}, {"records": ["tasks/a"]}):
        with pytest.raises(AutonomousManifestError) as info:
            validate_current_state(change)
        assert CANARY not in str(info.value)
    with pytest.raises(AutonomousManifestError, match="not urn:zeus:autonomous:1"):
        validate_autonomous_manifest(manifest(), packaged_policy())  # v1 validator never admits v2
    with pytest.raises(AutonomousManifestError, match="must be"):
        validate_any_manifest({**manifest(), "schema": "urn:zeus:autonomous:3"}, packaged_policy())
    with pytest.raises(AutonomousManifestError, match="current_state"):
        validate_any_manifest({k: v for k, v in manifest().items() if k != "current_state"}, packaged_policy())
    assert validate_any_manifest(v1_manifest(), packaged_policy())["schema"] == "urn:zeus:autonomous:1"


# ----- snapshot domain and adapter ----------------------------------------------------------------
def test_snapshot_reduces_rows_to_digests_and_whitelist_and_keeps_missing_unknown_and_found_apart():
    selection = CURRENT_STATE["records"]
    records = snapshot_records(selection, DB_ROWS)
    assert [r["state"] for r in records] == ["found", "missing", "unknown"]
    assert records[0]["sha256"] == digest(DB_ROWS[("tasks", "task-known")]) and records[0]["fields"] == {"status": "succeeded", "agent": "worker:implementation"}
    assert records[1] == {"bucket": "operations", "id": "op-missing", "state": "missing", "sha256": None, "fields": {}}
    assert records[2]["fields"] == {} and records[2]["sha256"] == digest(DB_ROWS[("autonomous_runs", "run-odd")])
    assert SECRET not in canonical(records)
    assert snapshot_records([{"bucket": "tasks", "id": "x"}], {("tasks", "x"): "not an object"})[0]["state"] == "unknown"
    clock = Clock()
    port = FakeSnapshotPort(clock)
    envelope_ = port.observe(selection, topic="t", run_id="council-001", base_revision=BASE, max_age_seconds=600)
    assert port.statements[0] == "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY" and port.statements[-1] == "ROLLBACK"
    assert any(s.startswith("SET LOCAL statement_timeout") for s in port.statements)
    assert envelope_["observed_at"] == clock.now and envelope_["expires_at"] == "2029-01-01T00:10:00+00:00"
    assert envelope_["isolation"] == "repeatable read read only" and len(envelope_["database_identity"]) == 64
    assert envelope_["database_identity"] == digest({"database": "zeus", "schema": "test_schema", "server_version": "18.0"})
    assert SECRET not in canonical(envelope_), "no row body, no DSN"
    other = FakeSnapshotPort(clock)
    same = other.observe(selection, topic="t", run_id="council-001", base_revision=BASE, max_age_seconds=600)
    assert snapshot_digest(same) == snapshot_digest(envelope_), "content-addressed"
    for mode in ("unavailable", "read_error", "connect_error"):
        with pytest.raises(SnapshotUnavailable) as info:
            FakeSnapshotPort(clock, mode).observe(selection, topic="t", run_id="council-001", base_revision=BASE, max_age_seconds=600)
        assert info.value.reason_code == "snapshot_unavailable" and SECRET not in str(info.value)
        # Owner probe (injected fault): the raw adapter error rode along on the exception chain.
        assert info.value.__cause__ is None and info.value.__context__ is None
        assert SECRET not in "".join(traceback.format_exception(info.value)), mode
    with pytest.raises(AutonomousManifestError):
        port.observe([{"bucket": "tasks", "id": "t" + str(i)} for i in range(21)], topic="t", run_id="r", base_revision=BASE, max_age_seconds=600)
    with pytest.raises(ContractError):
        ReadOnlySnapshot("dsn", connect=lambda *a, **k: None, connect_timeout=0)
    frozen = snapshot_digest(envelope_)
    common = dict(expected_digest=frozen, topic="t", run_id="council-001", base_revision=BASE, selection=selection)
    assert check_snapshot(envelope_, **common, now="2029-01-01T00:09:59+00:00")["records"][1]["state"] == "missing"
    with pytest.raises(SnapshotError, match="snapshot_stale"):
        check_snapshot(envelope_, **common, now="2029-01-01T00:10:00+00:00")
    assert check_snapshot(envelope_, **common, now=None), "integrity-only recheck"
    with pytest.raises(SnapshotError, match="snapshot_mismatch"):
        check_snapshot(envelope_, **{**common, "run_id": "council-002"}, now=clock.now)
    with pytest.raises(SnapshotError, match="snapshot_mismatch"):
        check_snapshot(envelope_, **{**common, "selection": selection[:2]}, now=clock.now)
    with pytest.raises(SnapshotError, match="snapshot_mismatch"):  # a well-formed envelope of other content is not the frozen one
        check_snapshot({**envelope_, "max_age_seconds": 601}, **common, now=clock.now)
    with pytest.raises(SnapshotError, match="snapshot_corrupt"):  # records that do not follow the envelope's own selection
        check_snapshot({**envelope_, "records": envelope_["records"][::-1]}, **common, now=clock.now)
    with pytest.raises(SnapshotError, match="snapshot_corrupt"):
        check_snapshot({**envelope_, "records": [{**envelope_["records"][0], "body": SECRET}] + envelope_["records"][1:]}, **common, now=clock.now)
    with pytest.raises(SnapshotError, match="snapshot_corrupt"):
        check_snapshot({**envelope_, "records": [{**envelope_["records"][1], "state": "found"}] + envelope_["records"][1:]}, **common, now=clock.now)
    with pytest.raises(SnapshotError, match="snapshot_corrupt"):
        snapshot_envelope(topic="t", run_id="r", base_revision=BASE, selection=selection, records=records, database_identity="x",
                          observed_at=clock.now, max_age_seconds=600)
    with pytest.raises(ContractError, match="required fields"):
        report_from_dba({**DBA_REPORT, "snapshot_digest": frozen, "extra": 1}, snapshot_digest_value=frozen, claim_ids={"c1"})
    with pytest.raises(ContractError, match="council_identity_mismatch"):
        report_from_dba({**DBA_REPORT, "snapshot_digest": "0" * 64}, snapshot_digest_value=frozen, claim_ids={"c1"})
    with pytest.raises(ContractError, match="claim_ids"):
        report_from_dba({**DBA_REPORT, "snapshot_digest": frozen, "claim_ids": ["c9"]}, snapshot_digest_value=frozen, claim_ids={"c1"})


def test_status_fields_are_finite_vocabularies_and_known_actor_syntax_never_arbitrary_tokens():
    """Regressions measured at 271e1ab: a normal colon-bearing actor was reduced to unknown, while an
    arbitrary token-shaped status was copied out verbatim (owner probe, injected rows)."""
    assert TASK_STATUSES == EXECUTION_STATUSES and OPERATION_STATUSES == {"running"} | OPERATION_TERMINAL
    assert RUN_STAGES == set(STAGES) | set(STAGES_V2)

    def state(bucket, body):
        record = snapshot_records([{"bucket": bucket, "id": "x"}], {(bucket, "x"): body})[0]
        assert record["sha256"] == digest(body) and (record["state"] == "found" or record["fields"] == {})
        return record["state"], record["fields"]
    for agent in ("worker:implementation", "lead:dba", "lead:improvement", "conductor"):
        assert state("tasks", {"status": "queued", "agent": agent}) == ("found", {"status": "queued", "agent": agent})
    for agent in ("worker:", "root:admin", "lead:a:b", "Lead:dba", "conductor:x", "lead:" + "a" * 65, "lead:dba " + SECRET, None, 7):
        assert state("tasks", {"status": "queued", "agent": agent})[0] == "unknown", agent
    for bucket, body in (("tasks", {"status": "exfiltrated-token", "agent": "lead:dba"}),  # token-shaped, not a status
                         ("tasks", {"agent": "lead:dba"}), ("tasks", {"status": None, "agent": "lead:dba"}),  # required status
                         ("tasks", {"status": "succeeded"}), ("tasks", {"status": True, "agent": "lead:dba"}),
                         ("operations", {"status": "succeeded", "lead_accepted": True}),  # a task status, not an operation status
                         ("operations", {"status": "accepted", "lead_accepted": "true"}), ("operations", {"lead_accepted": True}),
                         ("autonomous_runs", {"status": "running", "stage": "anything-goes"}),
                         ("autonomous_runs", {"status": "queued", "stage": "research"}), ("autonomous_runs", {"status": "running"}),
                         ("promotions", {"repository": "council-001"}), ("promotions", {"repository": "verified:"}),
                         ("promotions", {"repository": "verified:a/../b"}), ("promotions", {})):
        assert state(bucket, body) == ("unknown", {}), (bucket, body)
    assert state("operations", {"status": "running", "lead_accepted": None}) == ("found", {"status": "running", "lead_accepted": None})
    assert state("operations", {"status": "accepted", "lead_accepted": True})[0] == "found"
    # Key absence is not the nullable value (synthetic rows): only an explicit null/false/true is found.
    for status in ("running", "accepted"):
        assert state("operations", {"status": status}) == ("unknown", {}), status
        for accepted in (None, False, True):
            assert state("operations", {"status": status, "lead_accepted": accepted}) == ("found", {"status": status, "lead_accepted": accepted})
    assert snapshot_records([{"bucket": "operations", "id": "x"}], {})[0] == {"bucket": "operations", "id": "x", "state": "missing", "sha256": None, "fields": {}}
    assert state("autonomous_runs", {"status": "needs_user", "stage": "improvement_lead"})[0] == "found"
    assert state("promotions", {"repository": "verified:council-001"}) == ("found", {"repository": "verified:council-001"})
    # The consumer applies the same rule: a stored envelope cannot smuggle a value the producer would refuse.
    selection = [{"bucket": "tasks", "id": "x"}]
    records = snapshot_records(selection, {("tasks", "x"): {"status": "succeeded", "agent": "worker:implementation"}})
    good = snapshot_envelope(topic="t", run_id="r", base_revision=BASE, selection=selection, records=records,
                             database_identity="0" * 64, observed_at=Clock().now, max_age_seconds=600)
    assert good["records"][0]["fields"]["agent"] == "worker:implementation"
    for fields in ({"status": "exfiltrated-token", "agent": "worker:implementation"}, {"status": "succeeded", "agent": "root:admin"},
                   {"status": "succeeded"}, {"status": None, "agent": "worker:implementation"}):
        with pytest.raises(SnapshotError, match="snapshot_corrupt"):
            validate_snapshot({**good, "records": [{**good["records"][0], "fields": fields}]})
    with pytest.raises(SnapshotError, match="snapshot_corrupt"):
        validate_snapshot({**good, "records": [{**good["records"][0], "state": "unknown"}]})  # unknown exports no fields


def test_application_snapshot_refusal_keeps_no_raw_exception_chain():
    for mode in ("connect_error", "read_error", "unavailable", "raw"):
        svc, run, executor, budget, port = build(snapshot_mode=mode)
        if mode == "raw":  # a port that leaks its own driver error instead of mapping it (injected fault)
            port.observe = lambda selection, **binding: (_ for _ in ()).throw(OSError("password " + SECRET))
        claimed = run.claim(valid(), IDENTITY, BOUND_GOAL)
        with pytest.raises(AutonomousRefused) as info:
            run._observe(valid(), claimed["row"])
        assert info.value.reason_code == "snapshot_unavailable" and info.value.__cause__ is None and info.value.__context__ is None
        assert SECRET not in "".join(traceback.format_exception(info.value)), mode


# ----- normal ---------------------------------------------------------------------------------------
def test_critical_improvement_finding_is_converted_once_and_reaches_the_event_and_the_conductor_intact():
    """Regression measured at 271e1ab: the improvement output went through `attacker_findings` twice and
    the second pass refused the already converted critical finding (trigger/impact/mitigation gone)."""
    critical = {"id": "f0", "criterion": "focused tests pass", "severity": "critical", "scenario": "stale row read",
                "claim_ids": ["c1"], "trigger": "snapshot older than max age", "impact": "wrong design", "mitigation": "guard"}
    outputs = {"improvement_lead": {**IMPROVEMENT, "findings": [critical] + IMPROVEMENT["findings"]},
               "conductor": {**ROLE_OUTPUTS["arbiter"], "dispositions": [{"finding_id": "f0", "decision": "resolved", "reason": "guarded"}]
                             + ROLE_OUTPUTS["arbiter"]["dispositions"]}}
    svc, run, executor, budget, port = build(outputs=outputs)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and receipt["reason_code"] == "promoted", receipt["reason_code"]
    assert receipt["residuals"]["critical"] == [{"id": "f0", "status": "resolved"}]
    with svc.store.transaction() as tx:
        event = [e for e in tx.scan("dge_events") if e["role"] == "attacker"][0]
        found = {f["id"]: f for f in event["event"]["payload"]["findings"]}
        assert found["f0"]["scenario"].count("trigger: ") == 1 == found["f0"]["scenario"].count("mitigation: "), "one conversion"
        assert set(found["f0"]) == {"id", "criterion", "severity", "scenario", "claim_ids"}
        conductor = [t for t in tx.scan("tasks") if t["agent"] == "conductor"][0]["message"]["what"]["details"]
        assert conductor["improvement_proposal"]["findings"][0] == critical, "the conductor sees the raw, complete finding"
    derived = council_output("improvement_lead", {**outputs["improvement_lead"], "snapshot_digest": "1" * 64, "report_digest": "2" * 64},
                             {"snapshot_digest": "1" * 64, "report_digest": "2" * 64}, {"c1"})
    assert derived["event_payload"]["findings"][0] == critical, "raw payload: event_from_role owns the single conversion"


@pytest.mark.parametrize("role, calls", [("research_lead", 3), ("improvement_lead", 4)])
def test_unknown_claim_id_in_a_lead_contribution_is_refused_before_the_next_role(role, calls):
    base = {"research_lead": ROLE_OUTPUTS["proposer"], "improvement_lead": IMPROVEMENT}[role]
    svc, run, executor, budget, port = build(outputs={role: {**base, "claim_ids": ["c1", "c-not-in-packet"]}})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "debate_refused:ContractError" and executor.calls == ORDER[:calls]
    assert receipt["promotion"] is None
    with svc.store.transaction() as tx:
        assert len(tx.scan("dge_events")) == calls - 3, "the refused contribution never became an event"
    for bad in (["c9"], ["c1", "c1"], "c1", [1]):
        with pytest.raises(ContractError, match="claim_ids"):
            council_output("improvement_lead", {**IMPROVEMENT, "claim_ids": bad, "snapshot_digest": "1" * 64, "report_digest": "2" * 64},
                           {"snapshot_digest": "1" * 64, "report_digest": "2" * 64}, {"c1"})


def test_normal_council_cycle_uses_real_agents_shares_one_report_reaches_the_conductor_and_promotes():
    svc, run, executor, budget, port = build()
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and receipt["reason_code"] == "promoted" and receipt["exit_code"] == 0
    assert executor.calls == ORDER and receipt["starts"]["reserved"] == 7 == receipt["starts"]["settled"] == len(budget.reserved)
    assert receipt["max_starts"] == 7 and port.calls == 1 and receipt["topology"]["version"] == 2
    assert [s["provider"] for s in receipt["starts"]["slots"]] == ["codex"] * 5 + ["claude", "codex"]
    assert set(receipt["roles"]) == {"researcher", "dba", "research_lead", "improvement_lead", "conductor"}
    assert {r: b["agent"] for r, b in receipt["roles"].items()} == {"researcher": "lead:researcher", "dba": "lead:dba",
                                                                    "research_lead": "lead:research", "improvement_lead": "lead:improvement",
                                                                    "conductor": "conductor"}
    assert set(receipt["durations"]) == {"researcher", "dba", "research_lead", "improvement_lead", "conductor", "implementation", "promotion"}
    assert [h["to"] for h in receipt["history"]] == ["research", "packet", "snapshot", "dba", "research_lead", "improvement_lead",
                                                     "conductor", "implementation", "promotion"]
    snapshot, report = receipt["snapshot"], receipt["report"]
    assert snapshot["coverage"] == {"selected": 3, "found": 1, "missing": 1, "unknown": 1} and snapshot["ref"].startswith("sha256:")
    assert report["snapshot_digest"] == snapshot["sha256"] and report["task_id"] == receipt["roles"]["dba"]["task_id"]
    assert receipt["promotion"]["repository"] == "verified:council-001" and len(receipt["promotion"]["nodes"]) == 5
    with svc.store.transaction() as tx:
        tasks = {t["agent"]: t for t in tx.scan("tasks") if t["message"]["what"]["action"] == "dge_role"}
        for role, agent in (("research_lead", "lead:research"), ("improvement_lead", "lead:improvement"), ("conductor", "conductor")):
            details = tasks[agent]["message"]["what"]["details"]
            assert (details["snapshot_digest"], details["report_digest"]) == (snapshot["sha256"], report["sha256"]), role
            assert details["dba_report"]["summary"] == DBA_REPORT["summary"] and details["relay"]["via"] == "conductor"
        conductor = tasks["conductor"]
        assert conductor["message"]["who"] == {"sender": "conductor", "recipient": "conductor", "owner": "conductor"}
        assert conductor["message"]["what"]["details"]["improvement_proposal"]["decision"] == "improve"
        assert conductor["message"]["what"]["details"]["improvement_proposal"]["transition"]["rollback"] == "revert"
        events = {e["role"]: e for e in tx.scan("dge_events")}
        assert set(events) == {"proposer", "attacker", "arbiter"} and set(events["attacker"]["event"]["payload"]) == {"findings"}, "internal slots"
        assert events["attacker"]["binding"]["agent"] == "lead:improvement" and events["arbiter"]["binding"]["agent"] == "conductor"
        design = tx.get("knowledge_nodes", "verified:council-001:design")["body"]
        assert design["council"]["dba"]["task_id"] == report["task_id"] and design["council"]["snapshot"]["sha256"] == snapshot["sha256"]
        assert design["council"]["report"]["sha256"] == report["sha256"] and design["council"]["topology"]["roles"]["dba"]["agent"] == "lead:dba"
        promotion = tx.get("promotions", "council-001")
        assert promotion["evidence"]["snapshot_sha256"] == snapshot["sha256"] and promotion["evidence"]["dba_reservation_id"] == "res-" + report["task_id"]
        inbox = [row["result"] for row in tx.scan("workflow_inbox")]
        assert len(inbox) >= 5, "the leads' and the conductor's own task.result went through the workflow"
        assert executor.artifacts.document(snapshot["ref"])["records"][1]["state"] == "missing"
    text = json.dumps(receipt) + json.dumps(AutonomousRun(svc).status("council-001"))
    assert SECRET not in text and CANARY not in text
    replay = build()[1]
    replay.service = svc
    cached = replay.run(valid(), IDENTITY, BOUND_GOAL)
    assert cached["cached"] is True and cached["starts"] == receipt["starts"] and port.calls == 1


def test_v1_manifest_through_the_council_class_runs_the_v1_flow_with_six_starts_and_no_snapshot():
    svc, run, executor, budget, port = build()
    receipt = run.run(validate_autonomous_manifest(v1_manifest(), packaged_policy()), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and receipt["max_starts"] == 6 and port.calls == 0 and receipt["snapshot"] is None
    assert executor.calls == ["lead:researcher", "lead:proposer", "lead:attacker", "lead:arbiter", "worker:implementation", "lead:improvement"]
    assert receipt["topology"]["version"] == 1


# ----- unknown / failure / time / ownership ---------------------------------------------------------
@pytest.mark.parametrize("mode, code", [("unavailable", "snapshot_unavailable"), ("read_error", "snapshot_unavailable"),
                                        ("connect_error", "snapshot_unavailable"), ("malformed", "snapshot_corrupt")])
def test_unavailable_or_malformed_snapshot_refuses_after_research_with_no_further_start(mode, code):
    svc, run, executor, budget, port = build(snapshot_mode=mode)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == code and executor.calls == ["lead:researcher"]
    assert receipt["snapshot"] is None and receipt["stage"] == "snapshot"
    with svc.store.transaction() as tx:
        assert tx.get("dge_sessions", "council-001.design")["state"] == "proposal" and tx.scan("knowledge_nodes") == []


def test_stale_snapshot_stops_at_the_next_role_boundary_without_refresh_or_extra_start():
    clock = Clock()
    svc, run, executor, budget, port = build(clock=clock)
    original = executor.execute_one

    def slow_research_lead(agent, expected=None):
        row = original(agent, expected)
        if agent == "lead:research":
            clock.now = "2029-01-01T00:10:00+00:00"  # max_age 600s elapsed (fixture clock)
        return row
    executor.execute_one = slow_research_lead
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "snapshot_stale" and port.calls == 1
    assert executor.calls == ["lead:researcher", "lead:dba", "lead:research"] and receipt["stage"] == "research_lead"


def test_corrupt_or_missing_frozen_snapshot_and_swapped_report_identity_refuse_before_the_next_role():
    svc, run, executor, budget, port = build()
    original = executor.execute_one

    def corrupt_after_dba(agent, expected=None):
        row = original(agent, expected)
        if agent == "lead:dba":
            with svc.store.transaction() as tx:
                executor.artifacts.corrupt(tx.get("autonomous_runs", "council-001")["snapshot"]["ref"])
        return row
    executor.execute_one = corrupt_after_dba
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "snapshot_corrupt" and executor.calls == ["lead:researcher", "lead:dba"]
    svc, run, executor, budget, port = build()
    original = executor.execute_one

    def drop_after_dba(agent, expected=None):
        row = original(agent, expected)
        if agent == "lead:dba":
            with svc.store.transaction() as tx:
                executor.artifacts.bodies.pop(tx.get("autonomous_runs", "council-001")["snapshot"]["ref"][7:])
        return row
    executor.execute_one = drop_after_dba
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "snapshot_missing" and executor.calls == ["lead:researcher", "lead:dba"]
    svc, run, executor, budget, port = build(swap_report=True)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "council_identity_mismatch" and executor.calls == ORDER[:4]
    svc, run, executor, budget, port = build(foreign_dba=True)  # the DBA names a digest it was never given
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "report_invalid" and executor.calls == ["lead:researcher", "lead:dba"]
    svc, run, executor, budget, port = build(shared_thread=True)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "role_session_shared" and executor.calls == ORDER[:3]


def test_unrelayed_dba_report_wrong_agent_and_missing_role_artifact_stop_the_run():
    svc, run, executor, budget, port = build()
    original = executor.execute_one

    def silent_dba(agent, expected=None):
        row = original(agent, expected)
        if agent == "lead:dba":
            with svc.store.transaction() as tx:
                for key in [r["message"]["message_id"] for r in tx.scan("outbox") if r["message"]["type"] == "task.result"]:
                    tx.put("outbox", key, {"message": tx.get("outbox", key)["message"], "sent": True})  # never published (fixture)
        return row
    executor.execute_one = silent_dba
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "report_not_relayed" and executor.calls == ["lead:researcher", "lead:dba"]
    svc, run, executor, budget, port = build(wrong_agent=True)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "role_task_unbound" and executor.calls == ["lead:researcher"]
    svc, run, executor, budget, port = build(evidence="none")
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "evidence_missing" and executor.calls == ["lead:researcher"] and port.calls == 0


def test_deadline_and_start_cap_bound_the_council_and_rejected_review_never_promotes():
    svc, run, executor, budget, port = build()
    with pytest.raises(AutonomousRefused, match="deadline_expired"):
        run.run(valid(deadline="2000-01-01T00:00:00+00:00"), IDENTITY, BOUND_GOAL)
    assert executor.calls == [] and port.calls == 0
    svc, run, executor, budget, port = build()
    run.budget = FakeBudget(refuse_after=6)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "exhausted" and receipt["reason_code"] == "operation_exhausted" and len(executor.calls) == 6
    svc, run, executor, budget, port = build(verdict=False)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "rejected" and receipt["reason_code"] == "review_rejected" and receipt["promotion"] is None
    with svc.store.transaction() as tx:
        assert tx.get("promotions", "council-001") is None and tx.scan("knowledge_nodes") == []
    svc, run, executor, budget, port = build()
    run.claim(valid(), IDENTITY, BOUND_GOAL)
    with pytest.raises(AutonomousRefused, match="running_residue"):
        build()[1].__class__(svc, executor, Bus(), Workflow(svc.store, svc.org), FakeBudget(), Collector()).run(valid(), IDENTITY, BOUND_GOAL)


# ----- promotion --------------------------------------------------------------------------------------
def test_tampered_dba_report_or_snapshot_cannot_promote_even_with_an_accepted_operation():
    svc, run, executor, budget, port = build()
    original = executor.decide_one

    def tamper_report(agent, expected=None):
        row = original(agent, expected)
        with svc.store.transaction() as tx:
            dba = tx.get("tasks", tx.get("autonomous_runs", "council-001")["report"]["task_id"])
            dba["result"]["summary"] = "everything is fine " + SECRET  # row edited after binding (fixture)
            tx.put("tasks", dba["id"], dba)
        return row
    executor.decide_one = tamper_report
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "promotion_report_unproven:evidence_answer_mismatch"
    assert receipt["operation"]["status"] == "accepted" and receipt["promotion"] is None and SECRET not in json.dumps(receipt)
    svc, run, executor, budget, port = build()
    original = executor.decide_one

    def tamper_snapshot(agent, expected=None):
        row = original(agent, expected)
        with svc.store.transaction() as tx:
            executor.artifacts.corrupt(tx.get("autonomous_runs", "council-001")["snapshot"]["ref"])
        return row
    executor.decide_one = tamper_snapshot
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "promotion_snapshot_unproven:snapshot_corrupt" and receipt["promotion"] is None
    with svc.store.transaction() as tx:
        assert tx.get("promotions", "council-001") is None and tx.scan("knowledge_nodes") == []
    svc, run, executor, budget, port = build(evidence="verdict", verdict=False)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "promotion_evidence_unproven:evidence_answer_mismatch", "worker/reviewer gates unchanged"


# ----- hierarchy ----------------------------------------------------------------------------------
def test_only_the_conductor_arbitration_self_loop_is_authorized():
    org = organization()
    own = envelope("task.assign", "conductor", "conductor", "dge_role", {"role": "conductor"}, "c")
    org.authorize(own)
    org.authorize(envelope("task.result", "conductor", "conductor", "dge_role", {"task_id": "t", "result": {}}, "c"))
    for message in (envelope("task.assign", "conductor", "conductor", "dge_role", {"role": "arbiter"}, "c"),
                    envelope("task.assign", "conductor", "conductor", "plan", {"role": "conductor"}, "c"),
                    envelope("task.assign", "lead:improvement", "lead:improvement", "dge_role", {"role": "conductor"}, "c"),
                    envelope("task.assign", "worker:implementation", "worker:implementation", "implement", {}, "c"),
                    envelope("task.assign", "lead:dba", "lead:improvement", "dge_role", {"role": "improvement_lead"}, "c"),
                    envelope("task.result", "lead:dba", "lead:improvement", "dge_role", {"task_id": "t", "result": {}}, "c"),
                    envelope("task.result", "conductor", "conductor", "implement", {"task_id": "t", "result": {}}, "c"),
                    envelope("review.result", "worker:implementation", "conductor", "review", {}, "c")):
        with pytest.raises(ContractError):
            org.authorize(message)
    org.authorize(envelope("task.result", "lead:dba", "conductor", "dge_role", {"task_id": "t", "result": {}}, "c"))
    org.authorize(envelope("task.assign", "conductor", "lead:dba", "dge_role", {"role": "dba"}, "c"))
    # A foreign-run message on the conductor stream during the relay stops the run instead of being consumed.
    svc, run, executor, budget, port = build()
    run.bus.publish({**envelope("task.result", "lead:dba", "conductor", "dge_role", {"task_id": "x", "result": {}}, "autonomous:other"),
                     "when": {"created_at": "2029-01-01T00:00:00+00:00", "deadline": None, "after": []}})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "foreign_message" and executor.calls == ["lead:researcher", "lead:dba"]
    with svc.store.transaction() as tx:
        assert tx.get("tasks", "x") is None


def test_dba_task_details_carry_the_redacted_snapshot_only():
    svc, run, executor, budget, port = build()
    run.run(valid(), IDENTITY, BOUND_GOAL)
    with svc.store.transaction() as tx:
        dba = [t for t in tx.scan("tasks") if t["agent"] == "lead:dba"][0]
        details = dba["message"]["what"]["details"]
        assert details["snapshot"]["records"][0]["fields"] == {"status": "succeeded", "agent": "worker:implementation"}
        assert SECRET not in canonical(details) and evidence_ref_of(details) == tx.get("autonomous_runs", "council-001")["report"]["input_ref"]
        assert RESEARCH["claims"][0]["id"] in details["packet"]["claims"][0]["id"]

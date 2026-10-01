"""Shared S8 scenario steps (`research.council`): M7 `application/council.py` (`CouncilRun`: `__init__`, `_pipeline`, `_admit`,
`_role`, `_observe`, `_guard`, `_frozen_document`, `_relay`, `_recheck`; the module names `SNAPSHOT_SOURCE`, `SNAPSHOT_REFUSALS`,
`PROPOSAL_SECTION`, `CONSUMER_OVERFLOW`, `CONSUMER_REFUSAL_OUTCOMES`), characterized BEFORE the council module moves (DESIGN-s8 §2 row
`research.council_dge`, its council half, and §7 V12: the move goes to `coordination.application.council` in the NEXT pilot, so this
golden is placement-neutral: it observes SOURCE behaviour only; the branch table `branch-table-research.txt` section
`application/council.py`: 19 raise statements (17 `AutonomousRefused`/`ContractError` raises and 2 bare re-raises) plus the `require` in
`_pipeline`, each covered below or named unreachable with its reason).

- **c1_manifest**: M7 `test_v2_manifest_keeps_the_v1_canonical_form_...` (the domain input of the run, other family: `domain.council`; pinned here
  for the order "refused before any provider") and `test_v1_manifest_through_the_council_class_runs_the_v1_flow_...` (v1 through
  CouncilRun: the six starts of the autonomous flow), the v2 profile gate (`require` for a missing port or store), the module names.
- **c2_snapshot**: `_observe` (unavailable, malformed, the port's own refusal codes, `snapshot_mismatch`, the exception chain of M7
  `test_application_snapshot_refusal_keeps_no_raw_exception_chain`), `_guard` (stale at every boundary, corrupt or missing frozen
  document after each role, a swapped document, `snapshot_missing`), `_frozen_document` (every mapping), M7
  `test_unavailable_or_malformed_snapshot_...`, `test_stale_snapshot_stops_...`, `test_corrupt_or_missing_frozen_snapshot_...`.
- **c3_roles**: `_pipeline` role loop (`report_invalid`, `council_identity_mismatch`, `role_session_shared`, `debate_refused:<code>`, the
  fixed field code), `_role` (the consumer overflow lifted only in its safe shape), `_admit` (the producer gates of
  `tests/test_council_input.py` that run through CouncilRun), M7 `test_critical_improvement_finding_is_converted_once_...`,
  `test_unknown_claim_id_in_a_lead_contribution_...`, `test_an_oversized_improvement_summary_...`.
- **c4_relay_recheck**: `_relay` (the unrelayed DBA report, the wrong sender, action, task), the wrong agent, the missing artifact,
  `_recheck` (a tampered report or snapshot, `report_mismatch`, every `promotion_*_unproven` code) with the digests before and after.
- **c5_bounds**: the deadline at every clock read, the start cap, a rejected review (M7 `test_deadline_and_start_cap_bound_the_council_...`),
  M7 `test_only_the_conductor_arbitration_self_loop_is_authorized` (the organization rules are another family; the foreign-message relay
  stop is this module's).
- **c6_normal**: M7 `test_normal_council_cycle_...` (the seven starts, the topology, the snapshot and the report on the receipt, the
  promotion with the digests, the replay), `test_dba_task_details_carry_the_redacted_snapshot_only`, the observer's snapshot events.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a target)
driver builds. The snapshot port is M7's own `ReadOnlySnapshot` driven by an injected FAKE `connect` (as M7's `tests/test_council.py`
drives it); the `artifacts` port is a LABELLED `put(body, source)` double with M7's `{"ref", "source"}` shape; the executor, the role
artifacts, the evidence source, the clock, the bus and the budget are the labelled doubles of `s8_autonomous` (CouncilRun subclasses
AutonomousRun) with M7's `CouncilExecutor` extension. No model, Git, provider, network, process or PostgreSQL is touched. Where a state
has no honest call path (a direct call over a finished run, a wrapped step) the case is LABELLED where it is made.
"""

from __future__ import annotations

import copy
import json
import traceback
from types import SimpleNamespace

import s5_operation as O
import s8_autonomous as A
import s8_research_program as R

CANARY, BASE, LATE, START, DEADLINE = A.CANARY, A.BASE, A.LATE, A.START, A.DEADLINE
IDENTITY, BOUND_GOAL = A.IDENTITY, A.BOUND_GOAL
RUN = "council-001"
SECRET = "SECRET-row-text-never-emitted"
CORRELATION = "autonomous:" + RUN
V2 = "urn:zeus:autonomous:2"
OLD = "2028-12-31T23:00:00+00:00"          # a snapshot observed (by its own clock) long before the run's clock
EXPIRY = "2029-01-01T00:10:00+00:00"       # observed_at (the run clock) + the 600 s max age
CURRENT_STATE = {"records": [{"bucket": "tasks", "id": "task-known"}, {"bucket": "operations", "id": "op-missing"},
                             {"bucket": "autonomous_runs", "id": "run-odd"}], "max_age_seconds": 600}
DB_ROWS = {("tasks", "task-known"): {"id": "task-known", "status": "succeeded", "agent": "worker:implementation", "error": SECRET},
           ("autonomous_runs", "run-odd"): {"id": "run-odd", "status": "running", "stage": "not a token!"}}
ORDER = ["lead:researcher", "lead:dba", "lead:research", "lead:improvement", "conductor", "worker:implementation", "lead:improvement"]
DBA_REPORT = {"summary": "task-known succeeded; op-missing absent at snapshot; run-odd unknown", "claim_ids": ["c1"],
              "unknowns": ["run-odd stage is not interpretable"]}
IMPROVEMENT = {"summary": "reuse the runbook path", "decision": "improve", "rationale": "extend rather than fork",
               "transition": {"compatibility": "additive", "rollback": "revert", "retirement": "none"}, "claim_ids": ["c1"],
               "findings": A.ROLE_OUTPUTS["attacker"]["findings"]}
WATCHED = ("autonomous_runs", "operations", "outbox") + A.PROMOTION_BUCKETS + ("dge_sessions", "dge_events")
KOREAN = "한"
canonical_digest = A.canonical_digest
get, scan, put, attempt, edit = A.get, A.scan, A.put, A.attempt, A.edit


# ---- manifests --------------------------------------------------------------------------------------------------------------
def manifest_document(**overrides):
    """M7 `manifest(**overrides)` (tests/test_council.py): the v1 document with the v2 schema, the council id and `current_state`."""
    document = {**A.manifest_document(), "schema": V2, "id": RUN, "current_state": copy.deepcopy(CURRENT_STATE)}
    document.update(overrides)
    return document


def valid(api, **overrides):
    return api.validate_council_manifest(manifest_document(**overrides), api.packaged_policy())


def valid_v1(api, **overrides):
    return api.validate_autonomous_manifest(A.manifest_document(**{"id": RUN, **overrides}), api.packaged_policy())


# ---- labelled doubles (M7 tests/test_council.py) ------------------------------------------------------------------------------
class FakeConnection:
    """LABELLED. M7 `FakeConnection`: a psycopg-shaped connection double that records statements and serves the fixed rows."""

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


class SnapshotPort:
    """LABELLED. M7 `FakeSnapshotPort`: M7's own `ReadOnlySnapshot` over the fake connection; `mode` injects unavailable, malformed,
    connect_error, read_error. Extensions: `fault` (an exception `observe` raises instead), `bind` (replacement binding values, so the
    port answers a VALID envelope of another topic/run/base/selection) and `at` (the port's own clock: the instant it observes)."""

    def __init__(self, api, clock, mode="ok", rows=None):
        self.api, self.clock, self.mode, self.calls, self.statements = api, clock, mode, 0, []
        self.rows = DB_ROWS if rows is None else rows
        self.fault, self.bind, self.at = None, {}, None

    def observe(self, selection, **binding):
        self.calls += 1
        if self.fault is not None:
            raise self.fault
        if self.mode == "unavailable":
            raise self.api.SnapshotUnavailable("snapshot_unavailable")
        if self.mode == "malformed":
            return {"records": [{"body": SECRET}]}
        selection = self.bind.get("selection", selection)
        binding = {**binding, **{k: v for k, v in self.bind.items() if k != "selection"}}

        def connect(dsn, **kw):
            if self.mode == "connect_error":
                raise OSError("could not connect to " + dsn)   # a driver error quoting the DSN (injected fault)
            return FakeConnection(self.rows, self.statements, fail_at="unnest" if self.mode == "read_error" else None)
        clock = (lambda: self.at) if self.at is not None else self.clock
        return self.api.ReadOnlySnapshot("postgresql://user:" + SECRET + "@host/db", connect=connect, clock=clock).observe(selection, **binding)


class SnapshotArtifacts:
    """LABELLED. M7 `SnapshotArtifacts`: the FileArtifacts-shaped `put(body, source)` over the role-artifact store; the answer keeps
    M7's `{"ref", "source"}` shape and the call is recorded."""

    def __init__(self, artifacts):
        self.artifacts, self.puts = artifacts, []

    def put(self, body, source):
        self.puts.append(source)
        return {"ref": self.artifacts.put(body), "source": source}


class CouncilArtifacts(A.Artifacts):
    """LABELLED. The autonomous artifact store plus `by_ref` (labelled seam): a reference mapped to an exception (raised) or a document
    (answered) instead of the stored bytes; every other reference is the content-addressed store as before."""

    def __init__(self, api):
        super().__init__(api)
        self.by_ref = {}

    def document(self, ref):
        if ref in self.by_ref:
            answer = self.by_ref[ref]
            if isinstance(answer, BaseException):
                raise answer
            return answer
        return super().document(ref)


class CouncilExecutor(A.Executor):
    """LABELLED. M7 `CouncilExecutor` (tests/test_council.py): the autonomous executor plus council roles that fill in the identities
    they were given and every lead role files its `task.result` to its parent through the outbox, as `Workflow.complete` does.
    `swap_report` makes the improvement lead name a foreign report digest; `foreign_dba` makes the DBA name a digest it was never
    given; `dba_report` replaces the fixture report."""

    def __init__(self, api, svc, artifacts, swap_report=False, foreign_dba=False, dba_report=None, **kwargs):
        super().__init__(api, svc, artifacts, **kwargs)
        self.swap_report, self.foreign_dba, self.dba_report = swap_report, foreign_dba, dba_report or DBA_REPORT

    def execute_one(self, agent, expected=None):
        with self.svc.store.transaction() as tx:
            details = tx.get("tasks", expected["id"])["message"]["what"]["details"]
        role = details["role"] if agent != "worker:implementation" else None
        if role == "dba":
            self.outputs["dba"] = {"snapshot_digest": "0" * 64 if self.foreign_dba else details["snapshot_digest"], **self.dba_report}
        elif role in {"research_lead", "improvement_lead", "conductor"}:
            identities = {"snapshot_digest": details["snapshot_digest"], "report_digest": details["report_digest"]}
            if role == "improvement_lead" and self.swap_report:
                identities["report_digest"] = "f" * 64
            base = {"research_lead": A.ROLE_OUTPUTS["proposer"], "improvement_lead": IMPROVEMENT, "conductor": A.ROLE_OUTPUTS["arbiter"]}[role]
            self.outputs[role] = {**self.outputs.get(role, base), **identities}
        task = super().execute_one(agent, expected)
        if role is not None and task["status"] == "succeeded":
            with self.svc.store.transaction() as tx:
                report = self.api.envelope("task.result", task["agent"], task["message"]["who"]["sender"], "dge_role",
                                           {"task_id": task["id"], "result": task["result"]}, task["message"]["correlation_id"], task["id"])
                tx.put("outbox", report["message_id"], {"message": report, "sent": False})
        return task


class RoleRefusedExecutor(CouncilExecutor):
    """LABELLED. M7 `ConsumerOverflowExecutor` (tests/test_council_input.py) for any one role: that role's task ends the way the real
    executor records its own refusal (task error = exception type + ': ' + the typed reason; status `retry` for the pre-entry path,
    `failed` once settled as not retryable); every other role runs as the council fixture does."""

    def __init__(self, api, svc, artifacts, role="conductor", error=None, status="retry", **kwargs):
        super().__init__(api, svc, artifacts, **kwargs)
        self.role, self.error, self.status = role, error, status

    def execute_one(self, agent, expected=None):
        with self.svc.store.transaction() as tx:
            task = tx.get("tasks", expected["id"])
        if task["message"]["what"]["details"].get("role") != self.role:
            return super().execute_one(agent, expected)
        self.calls.append(agent)
        with self.svc.store.transaction() as tx:
            task.update(attempt=1, generation=1, lease_owner="fixture", status=self.status, error=self.error)
            tx.put("tasks", task["id"], task)
        return task


def system(api, clock=None, snapshot_mode="ok", bus=None, budget=None, observer=None, port=True, store_port=True, executor_class=None,
           **executor):
    """M7 `build(clock=None, snapshot_mode="ok", **kwargs)`: a `Harness` over a `MemoryStore`, the labelled executor, the fake
    snapshot port and the `CouncilRun`. `port=False` / `store_port=False` leave out the snapshot port / the artifact store."""
    svc = api.Harness(api.MemoryStore(), api.organization())
    artifacts, clock = CouncilArtifacts(api), clock or A.Clock()
    fake = (executor_class or CouncilExecutor)(api, svc, artifacts, clock=clock, **executor)
    budget = budget or O.FakeBudget()
    budget.error = api.ContractError
    collector = O.Collector()
    bus = bus if bus is not None else O.Bus()
    snapshot = SnapshotPort(api, clock, snapshot_mode)
    snapshots = SnapshotArtifacts(artifacts)
    run = api.CouncilRun(svc, fake, bus, api.Workflow(svc.store, svc.org), budget, collector,
                         verify_sources=lambda packet: [{**s, "bytes": 1} for s in packet["sources"]], repository=A.REPO,
                         observer=observer, clock=clock, evidence=artifacts, snapshot=snapshot if port else None,
                         artifacts=snapshots if store_port else None)
    return SimpleNamespace(api=api, svc=svc, run=run, executor=fake, budget=budget, collector=collector, bus=bus, clock=clock,
                           artifacts=artifacts, snapshots=snapshots, port=snapshot, observer=observer)


# ---- observations ------------------------------------------------------------------------------------------------------------
def snap(store) -> dict:
    """The digests (and counts) of the watched buckets (the run, operation and outbox rows, the promotion buckets and the dge
    buckets) and of the whole store."""
    with store.transaction() as tx:
        rows = tx.records()
    out = {}
    for bucket in WATCHED:
        mine = sorted([r["id"], canonical_digest(r["body"])] for r in rows if r["bucket"] == bucket)
        out[bucket] = {"n": len(mine), "digest": canonical_digest(mine)}
    out["all"] = canonical_digest(sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows))
    return out


def refused(store, fn, *args, **kwargs):
    """A call with the store digests before and after (a refusal leaves the watched buckets as they were, or says how not)."""
    before = snap(store)
    result = attempt(fn, *args, **kwargs)
    after = snap(store)
    return {**result, "before": before, "after": after, "changed": [k for k in before if before[k] != after[k]]}


def view(receipt) -> dict:
    """The decision facts of a council receipt: the autonomous view plus the v2 facts (starts cap, topology, snapshot, report)."""
    base = A.receipt_view(receipt)
    snapshot, report = receipt.get("snapshot"), receipt.get("report")
    return {**base, "max_starts": receipt.get("max_starts"), "topology_version": (receipt.get("topology") or {}).get("version"),
            "history": [h["to"] for h in receipt.get("history") or []],
            "snapshot": None if snapshot is None else {
                "coverage": snapshot["coverage"], "ref_is_sha256": snapshot["ref"].startswith("sha256:"), "sha256": snapshot["sha256"],
                "observed_at": snapshot["observed_at"], "expires_at": snapshot["expires_at"], "keys": sorted(snapshot)},
            "report": None if report is None else {
                "keys": sorted(report), "sha256": report["sha256"], "snapshot_is_the_frozen_one": report["snapshot_digest"] == snapshot["sha256"],
                "relay_is_a_message": bool(report["relay_message_id"])},
            "leaks_secret": SECRET in json.dumps(receipt, sort_keys=True, default=str)}


def cycle(s, manifest=None, identity=None, goal=None):
    """`run` over the system, reported: the receipt view (or the refusal), the executor calls, the budget, the snapshot port's calls
    and the store digests before and after."""
    manifest = manifest if manifest is not None else valid(s.api)
    before = snap(s.svc.store)
    try:
        receipt = s.run.run(manifest, identity or IDENTITY, goal or BOUND_GOAL)
        outcome = view(receipt)
    except Exception as exc:   # the refusal is the characterized result
        receipt = None
        outcome = {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc)[:200]}
    row = get(s.svc.store, "autonomous_runs", manifest["id"])
    after = snap(s.svc.store)
    return {"outcome": outcome, "calls": list(s.executor.calls), "port_calls": s.port.calls,
            "reserved": [[b["provider"], b["model"]] for b in s.budget.reserved], "settled": len(s.budget.settled),
            "row": None if row is None else {"status": row["status"], "stage": row["stage"], "reason_code": row["reason_code"],
                                             "has_snapshot": bool(row.get("snapshot")), "has_report": bool(row.get("report"))},
            "before": before, "store": after, "changed": [k for k in before if before[k] != after[k]]}, receipt


def case(api, **options):
    """A fresh system and one `run`; the second value is the system (to read further)."""
    s = system(api, **options)
    result, _ = cycle(s)
    return result, s


def brief(result) -> dict:
    """The compact outcome of a case (the sweeps): reason, stage, status, the executor calls and the promotion."""
    outcome = result["outcome"]
    return {"status": outcome.get("status", outcome.get("refused")), "reason_code": outcome.get("reason_code"),
            "stage": outcome.get("stage"), "calls": len(result["calls"]), "port_calls": result["port_calls"],
            "promoted": bool((outcome.get("promotion") or {}).get("id")), "row_stage": (result["row"] or {}).get("stage")}


def tables(s) -> dict:
    """What a run left in the store: knowledge, promotion, the debate session, the events and the operation row."""
    return {"knowledge_nodes": len(scan(s.svc.store, "knowledge_nodes")), "promotions": len(scan(s.svc.store, "promotions")),
            "dge_session": (get(s.svc.store, "dge_sessions", RUN + ".design") or {}).get("state"),
            "dge_events": [e["role"] for e in scan(s.svc.store, "dge_events")],
            "tasks": sorted(t["agent"] for t in scan(s.svc.store, "tasks") if t["message"]["what"]["action"] == "dge_role"),
            "operation": get(s.svc.store, "operations", RUN + ".impl") is not None}


def after(s, agent, fn):
    """The labelled executor seam: the real fixture execution of `agent`, then `fn(s, row)` edits what it persisted."""
    A.after(s, agent, fn)


def outer(s, agent, fn):
    """The labelled OUTER executor seam (M7 `executor.execute_one = ...`): after the council executor has also filed the role's
    `task.result` to the outbox, `fn(s, row)` edits what is stored."""
    original = s.executor.execute_one

    def wrapped(name, expected=None):
        row = original(name, expected)
        if name == agent:
            fn(s, row)
        return row
    s.executor.execute_one = wrapped


def run_row(s):
    return get(s.svc.store, "autonomous_runs", RUN)


def snapshot_ref(s):
    return run_row(s)["snapshot"]["ref"]


def finished(api, **options):
    """A normal cycle run to its promotion, with what the module's direct calls need: the manifest, the run row, the `observed`
    value `_pipeline` hands `_guard`/`_recheck` (rebuilt from the row and the stored envelope) and the frozen report."""
    s = system(api, **options)
    manifest = valid(api)
    receipt = s.run.run(manifest, IDENTITY, BOUND_GOAL)
    return s, manifest, receipt


def observed_of(s, manifest):
    row = run_row(s)
    frozen = row["snapshot"]
    return {**frozen, "envelope": s.artifacts.document(frozen["ref"]), "selection": [dict(r) for r in manifest["current_state"]["records"]]}


# ---- c1 --------------------------------------------------------------------------------------------------------------------
def c1_manifest(api, ws):
    out = {}
    bound, v1 = valid(api), valid_v1(api)
    out["v2_canonical_form"] = {
        "v1_part_equal": {k: v for k, v in bound.items() if k not in {"schema", "current_state"}} == {k: v for k, v in v1.items() if k != "schema"},
        "current_state": bound["current_state"], "profile_v2": {k: api.profile(bound)[k] for k in ("version", "max_starts")},
        "profile_v1": {k: api.profile(v1)[k] for k in ("version", "max_starts")}}
    many = [{"bucket": "tasks", "id": "t" + str(i)} for i in range(21)]
    bad = {"empty": {"records": [], "max_age_seconds": 600}, "too_many": {"records": many, "max_age_seconds": 600},
           "duplicate": {"records": [{"bucket": "tasks", "id": "a"}, {"bucket": "tasks", "id": "a"}], "max_age_seconds": 600},
           "unknown_bucket": {"records": [{"bucket": "outbox", "id": "a"}], "max_age_seconds": 600},
           "unsafe_id": {"records": [{"bucket": "tasks", "id": "../a"}], "max_age_seconds": 600},
           "extra_field": {"records": [{"bucket": "tasks", "id": "a", "body": 1}], "max_age_seconds": 600},
           "age_bool": {"records": [{"bucket": "tasks", "id": "a"}], "max_age_seconds": True},
           "age_low": {"records": [{"bucket": "tasks", "id": "a"}], "max_age_seconds": 59},
           "age_high": {"records": [{"bucket": "tasks", "id": "a"}], "max_age_seconds": 3601},
           "age_text": {"records": [{"bucket": "tasks", "id": "a"}], "max_age_seconds": "600"}, "record_text": {"records": ["tasks/a"]}}
    for name, state in bad.items():   # M7 test_v2_manifest_...: refused before any provider (the validator is the domain family's)
        try:
            valid(api, current_state=state)
            result = {"valid": True}
        except Exception as exc:   # the refusal is the characterized result
            result = {"refused": type(exc).__name__, "message": str(exc)[:200], "leaks_canary": CANARY in str(exc)}
        out["refused_" + name] = result
    out["v1_validator_never_admits_v2"] = attempt(api.validate_autonomous_manifest, manifest_document(), api.packaged_policy())
    s = system(api)
    out["refused_before_any_provider"] = {**refused(s.svc.store, s.run.run, manifest_document(), IDENTITY, BOUND_GOAL),
                                          "executor_calls": list(s.executor.calls), "port_calls": s.port.calls}
    # M7 test_v1_manifest_through_the_council_class_runs_the_v1_flow_with_six_starts_and_no_snapshot
    s = system(api)
    result, receipt = cycle(s, valid_v1(api))
    out["v1_manifest_runs_the_v1_flow"] = {**result, "tables": tables(s), "same_calls_as_the_autonomous_v1_flow": result["calls"] == [
        "lead:researcher", "lead:proposer", "lead:attacker", "lead:arbiter", "worker:implementation", "lead:improvement"]}
    s = system(api, port=False, store_port=False)
    result, _ = cycle(s, valid_v1(api))
    out["v1_manifest_needs_neither_port_nor_store"] = {**result, "tables": tables(s)}
    twin, twin_receipt = A.cycle(A.system(api), valid_v1(api))   # the same manifest through the plain AutonomousRun
    out["v1_through_autonomous_run_agrees"] = {"calls_equal": twin["calls"] == result["calls"], "status_equal": twin["outcome"]["status"] == result["outcome"]["status"],
                                               "starts_equal": twin["outcome"]["starts"] == result["outcome"]["starts"],
                                               "max_starts": [twin_receipt["max_starts"], receipt["max_starts"]]}
    out["v1_replay_cached"] = {"cached": cycle(s, valid_v1(api))[0]["outcome"].get("cached")}
    # the v2 profile gate (`require`): a snapshot port and an artifact store are both needed, before any provider
    for name, options in (("no_snapshot_port", {"port": False}), ("no_artifact_store", {"store_port": False}),
                          ("neither", {"port": False, "store_port": False})):
        result, s = case(api, **options)
        out["v2_" + name] = {**result, "tables": tables(s)}
    # M7: a v2 manifest whose deadline already passed is refused at the claim, before any provider or database access
    s = system(api)
    out["v2_deadline_passed"] = {**refused(s.svc.store, s.run.run, valid(api, deadline="2000-01-01T00:00:00+00:00"), IDENTITY, BOUND_GOAL),
                                 "executor_calls": list(s.executor.calls), "port_calls": s.port.calls, "reserved": len(s.budget.reserved)}
    out["module_names"] = {"SNAPSHOT_SOURCE": api.SNAPSHOT_SOURCE, "SNAPSHOT_REFUSALS": sorted(api.SNAPSHOT_REFUSALS),
                           "PROPOSAL_SECTION": dict(sorted(api.PROPOSAL_SECTION.items())),
                           "CONSUMER_OVERFLOW": api.CONSUMER_OVERFLOW.pattern, "CONSUMER_REFUSAL_OUTCOMES": sorted(api.CONSUMER_REFUSAL_OUTCOMES)}
    s = system(api)
    out["constructor"] = {"snapshot_is_the_port": s.run.snapshot is s.port, "artifacts_is_the_store": s.run.artifacts is s.snapshots,
                          "evidence_is_kept": s.run.evidence is s.artifacts, "is_an_autonomous_run": isinstance(s.run, api.AutonomousRun)}
    bare = api.CouncilRun(s.svc)
    out["constructor"]["defaults"] = {"snapshot": bare.snapshot, "artifacts": bare.artifacts}
    return out


# ---- c2 --------------------------------------------------------------------------------------------------------------------
def observe_leaks(api, mode, fault=None):
    """M7 `test_application_snapshot_refusal_keeps_no_raw_exception_chain`: `_observe` over a claimed run."""
    s = system(api, snapshot_mode=mode)
    if mode == "raw":   # a port that leaks its own driver error instead of mapping it (injected fault)
        s.port.fault = OSError("password " + SECRET)
    claimed = s.run.claim(valid(api), IDENTITY, BOUND_GOAL)
    try:
        s.run._observe(valid(api), claimed["row"])
        return {"refused": None}
    except api.AutonomousRefused as exc:
        return {"reason_code": exc.reason_code, "cause_is_none": exc.__cause__ is None, "context_is_none": exc.__context__ is None,
                "traceback_leaks_secret": SECRET in "".join(traceback.format_exception(exc))}


def slow(s, agent, now):
    """M7 `slow_research_lead`: after `agent` executes the fixture clock moves to `now`."""
    def move(s, row):
        s.clock.now = now
    after(s, agent, move)


def c2_snapshot(api, ws):
    out = {}
    for mode in ("connect_error", "read_error", "unavailable", "raw"):
        out["observe_chain_" + mode] = observe_leaks(api, mode)
    for mode in ("unavailable", "read_error", "connect_error", "malformed"):   # M7 parametrization
        result, s = case(api, snapshot_mode=mode)
        out["refused_" + mode] = {**result, "tables": tables(s), "session_state": get(s.svc.store, "dge_sessions", RUN + ".design")["state"]}
    # the port's own refusal codes: only the four fixed `SNAPSHOT_REFUSALS` survive; anything else is `snapshot_unavailable`
    for name, fault in (("port_snapshot_stale", api.SnapshotUnavailable("snapshot_stale")), ("port_snapshot_corrupt", api.SnapshotUnavailable("snapshot_corrupt")),
                        ("port_snapshot_mismatch", api.SnapshotUnavailable("snapshot_mismatch")),
                        ("port_unknown_code", api.SnapshotUnavailable("something_else")), ("port_contract_error_without_code", api.ContractError(SECRET)),
                        ("port_runtime_error", RuntimeError(SECRET)), ("port_value_error", ValueError(SECRET))):
        s = system(api)
        s.port.fault = fault
        result, _ = cycle(s)
        out[name] = {**result, "tables": tables(s), "leaks_secret": SECRET in json.dumps(result, default=str)}
    # `snapshot_mismatch`: a VALID envelope that is not the one asked for (topic, run, base revision or selection)
    for name, bind in (("other_topic", {"topic": "another topic"}), ("other_run", {"run_id": "council-002"}),
                       ("other_base", {"base_revision": "e" * 40}),
                       ("other_selection", {"selection": CURRENT_STATE["records"][:2]})):
        s = system(api)
        s.port.bind = bind
        result, _ = cycle(s)
        out["mismatch_" + name] = {**result, "tables": tables(s), "snapshot_stored": s.snapshots.puts}
    # the frozen observation: stored once, content-addressed, only references and safe metadata on the row
    s = system(api)
    result, receipt = cycle(s)
    row = run_row(s)
    out["frozen_once"] = {"puts": s.snapshots.puts, "row_snapshot_keys": sorted(row["snapshot"]), "coverage": row["snapshot"]["coverage"],
                          "database_identity_len": len(row["snapshot"]["database_identity"]), "port_calls": s.port.calls,
                          "ref_resolves_to_the_envelope": s.artifacts.document(row["snapshot"]["ref"])["run_id"] == RUN,
                          "statements": [x[:40] for x in s.port.statements], "outcome": result["outcome"]["status"]}
    # `_guard` at every boundary: stale at the first guard (the port observed long ago), at each later role boundary and before the worker
    s = system(api)
    s.port.at = OLD
    result, _ = cycle(s)
    out["stale_at_the_first_guard"] = {**result, "tables": tables(s)}
    for agent, now, name in (("lead:research", EXPIRY, "stale_at_the_next_role_boundary"),   # M7 test_stale_snapshot_stops_...
                             ("lead:research", "2029-01-01T00:09:59+00:00", "fresh_one_second_before_the_expiry"),
                             ("lead:improvement", EXPIRY, "stale_after_the_improvement_lead"),
                             ("conductor", EXPIRY, "stale_before_the_implementation"),
                             ("lead:dba", "2029-01-01T00:20:00+00:00", "stale_after_the_dba_by_a_long_way")):
        s = system(api)
        slow(s, agent, now)
        result, _ = cycle(s)
        out[name] = {**result, "tables": tables(s), "snapshot_refreshed": s.port.calls != 1}
    # M7 test_corrupt_or_missing_frozen_snapshot_...: the persisted envelope after each role
    for agent in ("lead:dba", "lead:research", "lead:improvement", "conductor"):
        for name, damage in (("corrupt", lambda s: s.artifacts.corrupt(snapshot_ref(s))),
                             ("missing", lambda s: s.artifacts.bodies.pop(snapshot_ref(s)[7:]))):
            s = system(api)
            after(s, agent, lambda s, row, damage=damage: damage(s))
            result, _ = cycle(s)
            out["%s_after_%s" % (name, agent.split(":")[-1])] = {**result, "tables": tables(s)}
    # a swapped document under the frozen reference: another VALID observation, then shapes that are not an observation
    other = system(api)
    swapped = other.port.observe(CURRENT_STATE["records"], topic="another topic", run_id=RUN, base_revision=BASE, max_age_seconds=600)
    for name, document in (("swapped_valid_other_topic", swapped), ("swapped_not_a_snapshot", {"records": []}),
                           ("swapped_extra_field", {**swapped, "body": SECRET}), ("swapped_not_an_object", [1, 2])):
        s = system(api)
        after(s, "lead:dba", lambda s, row, document=document: s.artifacts.by_ref.__setitem__(snapshot_ref(s), document))
        result, _ = cycle(s)
        out[name] = {**result, "tables": tables(s)}
    # `_frozen_document`: every mapping of the evidence port's answer (a LABELLED direct call over a claimed run)
    s = system(api)
    s.artifacts.by_ref["sha256:ok"] = {"x": 1}
    for name, fault in (("evidence_corrupt", api.EvidenceUnavailable("evidence_corrupt")), ("evidence_invalid", api.EvidenceUnavailable("evidence_invalid")),
                        ("evidence_missing", api.EvidenceUnavailable("evidence_missing")), ("contract_error_without_code", api.ContractError("x")),
                        ("contract_error_other_code", type("Coded", (api.ContractError,), {"reason_code": "evidence_other"})("x")),
                        ("file_not_found", FileNotFoundError("x")), ("os_error", OSError(SECRET)), ("value_error", ValueError(SECRET)),
                        ("runtime_error", RuntimeError(SECRET)), ("returns_the_document", None)):
        s.artifacts.by_ref["sha256:f"] = fault if fault is not None else {"ok": True}
        result = attempt(s.run._frozen_document, "sha256:f")
        result["leaks_secret"] = SECRET in json.dumps(result)
        out["frozen_document_" + name] = result
    out["frozen_document_unknown_reference"] = attempt(s.run._frozen_document, "sha256:" + "0" * 64)
    out["frozen_document_not_a_reference"] = attempt(s.run._frozen_document, None)
    # `_guard`: a LABELLED direct call over a finished run (the row, the frozen values and the clock are the module's inputs)
    f, manifest, receipt = finished(api)
    row, observed = run_row(f), observed_of(f, manifest)
    out["guard_fresh"] = {"digest": canonical_digest(attempt(f.run._guard, manifest, row, observed)),
                          "refused": attempt(f.run._guard, manifest, row, observed).get("refused")}
    f.clock.now = EXPIRY
    out["guard_stale_at_the_expiry"] = attempt(f.run._guard, manifest, row, observed)
    f.clock.now = "2029-01-01T00:09:59+00:00"
    out["guard_fresh_a_second_before"] = {"refused": attempt(f.run._guard, manifest, row, observed).get("refused")}
    f.clock.now = LATE
    out["guard_deadline_first"] = attempt(f.run._guard, manifest, row, observed)
    f.clock.now = START
    out["guard_unchanged_store"] = {"snapshot_equal": snap(f.svc.store) == snap(f.svc.store)}
    out["guard_run_without_a_snapshot"] = attempt(f.run._guard, manifest, {"id": "ghost"}, observed)
    out["guard_recorded_digest_differs"] = attempt(f.run._guard, manifest, row, {**observed, "sha256": "0" * 64})
    out["guard_recorded_ref_differs"] = attempt(f.run._guard, manifest, row, {**observed, "ref": "sha256:" + "1" * 64})
    out["guard_recorded_expiry_differs"] = attempt(f.run._guard, manifest, row, {**observed, "expires_at": "2030-01-01T00:00:00+00:00"})
    out["guard_other_selection"] = attempt(f.run._guard, manifest, row, {**observed, "selection": observed["selection"][:2]})
    out["guard_other_topic"] = attempt(f.run._guard, valid(api, research={**manifest["research"], "topic": "another topic"}), row, observed)
    out["guard_other_run"] = attempt(f.run._guard, manifest, {**row, "id": "council-002"}, observed)
    return out


# ---- c3 --------------------------------------------------------------------------------------------------------------------
def with_outputs(**outputs):
    return {"outputs": outputs}


def research_lead(**changes):
    return {"research_lead": {**A.ROLE_OUTPUTS["proposer"], **changes}}


def improvement(**changes):
    return {"improvement_lead": {**IMPROVEMENT, **changes}}


def event_roles(s):
    return [e["role"] for e in scan(s.svc.store, "dge_events")]


def big_research():
    """M7 `big_research()` (tests/test_council_input.py): valid claims whose packet exceeds the 16384-byte initial allowance."""
    claims = [A.RESEARCH["claims"][0]] + [{"id": "c" + str(i), "kind": "fact", "text": "claim " + str(i) + " " + "x" * 3000,
                                           "source_ids": ["s1"]} for i in range(2, 9)]
    return {**A.RESEARCH, "claims": claims}


def findings(count, size):
    return [{"id": "f" + str(i), "criterion": "focused tests pass", "severity": "minor", "scenario": "s" + str(i) + " " + "z" * size,
             "claim_ids": ["c1"], "trigger": None, "impact": None, "mitigation": None} for i in range(1, count + 1)]


def c3_roles(api, ws):
    out = {}
    # M7 test_critical_improvement_finding_is_converted_once_and_reaches_the_event_and_the_conductor_intact
    critical = {"id": "f0", "criterion": "focused tests pass", "severity": "critical", "scenario": "stale row read", "claim_ids": ["c1"],
                "trigger": "snapshot older than max age", "impact": "wrong design", "mitigation": "guard"}
    outputs = {"improvement_lead": {**IMPROVEMENT, "findings": [critical] + IMPROVEMENT["findings"]},
               "conductor": {**A.ROLE_OUTPUTS["arbiter"], "dispositions": [{"finding_id": "f0", "decision": "resolved", "reason": "guarded"}]
                             + A.ROLE_OUTPUTS["arbiter"]["dispositions"]}}
    result, s = case(api, outputs=outputs)
    event = [e for e in scan(s.svc.store, "dge_events") if e["role"] == "attacker"][0]
    found = {f["id"]: f for f in event["event"]["payload"]["findings"]}
    conductor = [t for t in scan(s.svc.store, "tasks") if t["agent"] == "conductor"][0]["message"]["what"]["details"]
    out["critical_converted_once"] = {**result, "residuals": result["outcome"].get("residuals"), "tables": tables(s),
                                      "scenario_conversion_counts": [found["f0"]["scenario"].count("trigger: "), found["f0"]["scenario"].count("mitigation: ")],
                                      "event_finding_keys": sorted(found["f0"]), "conductor_sees_the_raw_finding": conductor["improvement_proposal"]["findings"][0] == critical}
    # M7 test_unknown_claim_id_in_a_lead_contribution_is_refused_before_the_next_role (parametrized: research_lead 3 calls, improvement_lead 4)
    for role, calls, base in (("research_lead", 3, A.ROLE_OUTPUTS["proposer"]), ("improvement_lead", 4, IMPROVEMENT)):
        result, s = case(api, outputs={role: {**base, "claim_ids": ["c1", "c-not-in-packet"]}})
        out["unknown_claim_" + role] = {**result, "tables": tables(s), "expected_calls": ORDER[:calls], "events_expected": calls - 3,
                                        "events": len(scan(s.svc.store, "dge_events"))}
    for name, bad in (("duplicate", ["c1", "c1"]), ("not_a_list", "c1"), ("not_a_token", [1])):
        result, s = case(api, outputs={"improvement_lead": {**IMPROVEMENT, "claim_ids": bad}})
        out["bad_claim_ids_" + name] = {**result, "tables": tables(s)}
    # M7 test_an_oversized_improvement_summary_stops_with_the_fixed_field_code_and_keeps_the_output
    long = ("SECRET-summary-body " * 400)[:6046]
    result, s = case(api, outputs={"improvement_lead": {**IMPROVEMENT, "summary": long}})
    [task] = [t for t in scan(s.svc.store, "tasks") if t["agent"] == "lead:improvement"]
    out["oversized_improvement_summary"] = {**result, "tables": tables(s), "task_keeps_every_character": task["result"]["summary"] == long,
                                            "receipt_leaks_the_body": "SECRET-summary-body" in json.dumps(result)}
    # the other fixed field codes (type, empty, too_long) of the improvement lead and the DBA's `report_invalid`
    for name, change in (("summary_empty", {"summary": "  "}), ("summary_type", {"summary": 5}), ("rationale_too_long", {"rationale": "r" * 4001}),
                         ("transition_rollback_too_long", {"transition": {**IMPROVEMENT["transition"], "rollback": "x" * 4001}}),
                         ("transition_retirement_empty", {"transition": {**IMPROVEMENT["transition"], "retirement": ""}}),
                         ("transition_missing_key", {"transition": {"compatibility": "additive"}}),
                         ("decision_unknown", {"decision": "guess"}), ("transition_with_reuse", {"decision": "reuse"})):
        result, s = case(api, outputs=improvement(**change))
        out["improvement_" + name] = {**result, "tables": tables(s)}
    for name, change in (("summary_too_long", {"summary": "d" * 4001}), ("unknowns_too_long", {"unknowns": ["u" * 1025]}),
                         ("unknowns_not_a_list", {"unknowns": "x"}), ("unknown_claim", {"claim_ids": ["c9"]}),
                         ("extra_field", {"extra": 1})):
        result, s = case(api, dba_report={**DBA_REPORT, **change})
        out["dba_" + name] = {**result, "tables": tables(s)}
    result, s = case(api, foreign_dba=True)   # M7: the DBA names a digest it was never given
    out["dba_foreign_snapshot_digest"] = {**result, "tables": tables(s)}
    result, s = case(api, swap_report=True)   # M7: the improvement lead names a foreign report digest
    out["swapped_report_identity"] = {**result, "tables": tables(s)}
    result, s = case(api, shared_thread=True)
    out["role_session_shared"] = {**result, "tables": tables(s)}
    for role, status, name in (("research_lead", "retry", "role_retry_research_lead"), ("research_lead", "failed", "role_failed_research_lead"),
                               ("dba", "failed", "role_failed_dba"), ("dba", "retry", "role_retry_dba"),
                               ("improvement_lead", "failed", "role_failed_improvement_lead")):
        result, s = case(api, executor_class=lambda api, svc, artifacts, role=role, status=status, **kw: RoleRefusedExecutor(
            api, svc, artifacts, role=role, error="RuntimeError: provider failed " + SECRET, status=status, **kw))
        out[name] = {**result, "tables": tables(s), "leaks_secret": SECRET in json.dumps(result, default=str)}
    result, s = case(api, role_status="failed")
    out["role_failed_researcher"] = {**result, "tables": tables(s)}
    # `debate_refused:<code>`: a DgeRefused of `sessions.submit` (a LABELLED seam moves the session's version under the lead)
    s = system(api)
    after(s, "lead:dba", lambda s, row: edit(s, "dge_sessions", RUN + ".design", version=9))
    result, _ = cycle(s)
    out["debate_refused_session_version"] = {**result, "tables": tables(s)}
    for name, agent, change in (("terminal", "lead:research", {"state": "rejected"}), ("packet_digest", "lead:dba", {"packet_digest": "0" * 64}),
                                ("round", "lead:dba", {"round": 2}), ("role_out_of_order", "lead:dba", {"state": "critique"}),
                                ("expired", "lead:dba", {"deadline": "2000-01-01T00:00:00+00:00"})):
        s = system(api)
        after(s, agent, lambda s, row, change=change: edit(s, "dge_sessions", RUN + ".design", **change))
        result, _ = cycle(s)
        out["debate_refused_session_" + name] = {**result, "tables": tables(s)}
    s = system(api)
    after(s, "lead:dba", lambda s, row: edit(s, "dge_sessions", RUN + ".design", owner="someone-else"))
    result, _ = cycle(s)
    out["debate_refused_session_owner"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"conductor": {**A.ROLE_OUTPUTS["arbiter"], "verdict": "bogus"}})
    out["debate_refused_conductor_verdict"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"conductor": {**A.ROLE_OUTPUTS["arbiter"], "dispositions": []}})
    out["debate_refused_conductor_dispositions"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"improvement_lead": {**IMPROVEMENT, "findings": [{**A.FINDING, "id": "f2", "severity": "critical"}]}})
    out["debate_refused_unsupported_critical"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"conductor": {k: v for k, v in A.ROLE_OUTPUTS["arbiter"].items() if k != "rationale"}})
    out["conductor_missing_field"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"conductor": {**A.ROLE_OUTPUTS["arbiter"], "verdict": "reject"}})
    out["conductor_reject_ends_the_design"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"conductor": {**A.ROLE_OUTPUTS["arbiter"], "verdict": "needs_research", "research_question": "which lock?",
                                                  "dispositions": [{"finding_id": "f1", "decision": "blocking", "reason": "r"}]}})
    out["conductor_needs_research"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"conductor": {**A.ROLE_OUTPUTS["arbiter"], "verdict": "revise"}})
    out["conductor_revise"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"researcher": {**A.RESEARCH, "needs_user": True, "user_question": "which doc?"}})
    out["researcher_needs_user"] = {**result, "tables": tables(s)}
    # `_admit` and the producer gates through the real CouncilRun (M7 tests/test_council_input.py, INJECTED oversized outputs)
    result, s = case(api, outputs={"researcher": big_research()})
    out["overflow_packet"] = {**result, "tables": tables(s), "receipt_leaks_content": "xxxx" in json.dumps(result)}
    result, s = case(api, dba_report={**DBA_REPORT, "unknowns": [KOREAN * 1024] * 8})
    out["overflow_dba_report"] = {**result, "tables": tables(s), "receipt_leaks_content": KOREAN in json.dumps(result, ensure_ascii=False)}
    result, s = case(api, outputs=research_lead(summary=KOREAN * 8000))
    out["overflow_research_proposal"] = {**result, "tables": tables(s), "events": event_roles(s)}
    result, s = case(api, outputs=improvement(summary=KOREAN * 4000, rationale=KOREAN * 4000, transition={
        "compatibility": KOREAN * 4000, "rollback": KOREAN * 4000, "retirement": KOREAN * 4000}))
    out["overflow_improvement_proposal"] = {**result, "tables": tables(s), "events": event_roles(s)}
    result, s = case(api, outputs={**improvement(findings=findings(8, 3900))})
    out["overflow_improvement_findings"] = {**result, "tables": tables(s), "events": event_roles(s)}
    # CONTROL (M7): earlier unused capacity lets a report and findings over the retired ceilings reach the promotion
    many = findings(4, 2500)
    conductor = {**A.ROLE_OUTPUTS["arbiter"], "dispositions": [{"finding_id": f["id"], "decision": "deferred", "reason": "backlog"} for f in many]}
    result, s = case(api, dba_report={**DBA_REPORT, "summary": KOREAN * 4000}, outputs={"improvement_lead": {**IMPROVEMENT, "findings": many},
                                                                                       "conductor": conductor})
    out["control_over_the_retired_ceilings_promotes"] = {**result, "tables": tables(s)}
    # `_admit` called directly (a static gate): the section, the value and the committed prefix are its inputs
    out["admit_direct"] = {
        "small_packet": attempt(api.CouncilRun._admit, "packet", {"claims": []}, {}),
        "packet_over_its_reservation": attempt(api.CouncilRun._admit, "packet", {"text": "x" * 16400}, {}),
        "unknown_section": attempt(api.CouncilRun._admit, "nope", {"a": 1}, {}),
        "prefix_with_a_hole": attempt(api.CouncilRun._admit, "research_proposal", {"a": 1}, {"packet": {"a": 1}}),
        "report_after_the_packet": attempt(api.CouncilRun._admit, "dba_report", {"summary": "ok"}, {"packet": {"a": 1}}),
        "committed_unchanged": None}
    committed = {"packet": {"a": 1}}
    api.CouncilRun._admit("dba_report", {"summary": "ok"}, committed)
    out["admit_direct"]["committed_unchanged"] = committed
    # `_role`: the consumer gate's refusal lifted only in its exact safe shape (M7 test_consumer_gate_refusal_reaches_the_run_...)
    for status in ("retry", "failed"):
        for label, error in (("host_overhead", "CouncilInputOverflow: needs_scope_split:host_overhead:4721/4096"),
                             ("required", "CouncilInputOverflow: needs_scope_split:required:40961/40960"),
                             ("improvement_proposal", "CouncilInputOverflow: needs_scope_split:improvement_proposal:14867/14866"),
                             ("not_digits", "CouncilInputOverflow: needs_scope_split:packet:<script>/16384"),
                             ("other_type", "RuntimeError: needs_scope_split:packet:1/1"),
                             ("missing_input", "ContractError: Council delivery input missing: packet"),
                             ("beyond_prefix", "ContractError: Council input beyond the research_lead prefix: improvement_proposal"),
                             ("trailing_text", "CouncilInputOverflow: needs_scope_split:packet:1/2\nextra"),
                             ("uppercase_section", "CouncilInputOverflow: needs_scope_split:Packet:1/2"), ("no_error", None)):
            result, s = case(api, executor_class=lambda api, svc, artifacts, error=error, status=status, **kw: RoleRefusedExecutor(
                api, svc, artifacts, role="conductor", error=error, status=status, **kw))
            [task] = [t for t in scan(s.svc.store, "tasks") if t["agent"] == "conductor"]
            out["consumer_%s_%s" % (status, label)] = {**result, "task": [task["status"], task["error"]], "conductor_starts": result["calls"].count("conductor")}
    result, s = case(api, executor_class=lambda api, svc, artifacts, **kw: RoleRefusedExecutor(
        api, svc, artifacts, role="dba", error="CouncilInputOverflow: needs_scope_split:dba_report:5000/4480", status="retry", **kw))
    out["consumer_lifted_for_the_dba"] = {**result, "tables": tables(s)}
    result, s = case(api, executor_class=lambda api, svc, artifacts, **kw: RoleRefusedExecutor(
        api, svc, artifacts, role="dba", error=5, status="retry", **kw))
    out["consumer_error_not_text"] = {**result, "tables": tables(s)}
    return out


# ---- c4 --------------------------------------------------------------------------------------------------------------------
def relayed(api, rows, sender="lead:dba", task_id="t-1"):
    """`_relay` over a scripted bus and a stub workflow (LABELLED direct call): the relayed message id or the refusal."""
    bus = A.ScriptedBus(rows, api)
    s = system(api, bus=bus)
    s.run.workflow = A.StubWorkflow(api, s.svc)
    before = snap(s.svc.store)
    result = attempt(s.run._relay, CORRELATION, task_id, sender)
    return {**result, "acked": list(bus.acked), "dead_letters": list(bus.dead), "handled": len(s.run.workflow.handled),
            "changed": [k for k, v in before.items() if v != snap(s.svc.store)[k]]}


def result_message(api, sender="lead:dba", recipient="conductor", action="dge_role", task_id="t-1", correlation=CORRELATION, kind="task.result"):
    details = {"task_id": task_id, "result": {}} if kind == "task.result" else {"role": "dba"}
    return api.envelope(kind, sender, recipient, action, details, correlation)


def c4_relay_recheck(api, ws):
    out = {}
    # M7 test_unrelayed_dba_report_wrong_agent_and_missing_role_artifact_stop_the_run
    def silence(s, row):
        with s.svc.store.transaction() as tx:
            for r in tx.scan("outbox"):
                if r["message"]["type"] == "task.result":
                    tx.put("outbox", r["message"]["message_id"], {"message": r["message"], "sent": True})   # never published (fixture)
    for name, agent in (("unrelayed_dba_report", "lead:dba"), ("unrelayed_research_lead_result_is_not_needed", "lead:research")):
        s = system(api)
        outer(s, agent, silence)
        result, _ = cycle(s)
        out[name] = {**result, "tables": tables(s)}
    s = system(api)
    outer(s, "conductor", silence)   # the self-arbitration result goes through the workflow too
    result, _ = cycle(s)
    out["unrelayed_conductor_result"] = {**result, "tables": tables(s)}
    result, s = case(api, wrong_agent=True)
    out["wrong_agent_role_task_unbound"] = {**result, "tables": tables(s)}
    s = system(api)
    after(s, "lead:dba", lambda s, row: edit(s, "tasks", row["id"], agent="lead:improvement"))
    result, _ = cycle(s)
    out["wrong_agent_on_the_dba_task"] = {**result, "tables": tables(s)}
    result, s = case(api, evidence="none")
    out["missing_role_artifact"] = {**result, "tables": tables(s)}
    result, s = case(api, evidence="corrupt")
    out["corrupt_role_artifact"] = {**result, "tables": tables(s)}
    result, s = case(api, evidence="unrelated")
    out["unrelated_role_artifact"] = {**result, "tables": tables(s)}
    s = system(api)
    after(s, "lead:dba", lambda s, row: edit(s, "tasks", row["id"], result={**row["result"], "basis_revision": "9" * 40}))
    result, _ = cycle(s)
    out["dba_basis_revision_changed"] = {**result, "tables": tables(s)}
    # `_relay` direct over a scripted bus: which handled message counts as the relayed report
    mine = result_message(api)
    out["relay_direct_the_report"] = relayed(api, [("1-0", {"body": mine})])
    out["relay_direct_empty_bus"] = relayed(api, [])
    out["relay_direct_other_sender"] = relayed(api, [("1-0", {"body": result_message(api, sender="lead:research")})])
    out["relay_direct_other_sender_argument"] = relayed(api, [("1-0", {"body": mine})], sender="conductor")
    out["relay_direct_other_task"] = relayed(api, [("1-0", {"body": result_message(api, task_id="t-2")})])
    out["relay_direct_other_action"] = relayed(api, [("1-0", {"body": result_message(api, action="implement")})])
    out["relay_direct_assign_not_result"] = relayed(api, [("1-0", {"body": result_message(api, kind="task.assign", sender="conductor", recipient="conductor")})])
    out["relay_direct_foreign"] = relayed(api, [("1-0", {"body": result_message(api, correlation="autonomous:other")})])
    out["relay_direct_second_message_is_the_report"] = relayed(api, [("1-0", {"body": result_message(api, task_id="t-2")}),
                                                                      ("2-0", {"body": mine})])
    out["relay_direct_first_match_wins"] = relayed(api, [("1-0", {"body": mine}), ("2-0", {"body": mine})])
    # M7 test_only_the_conductor_arbitration_self_loop_is_authorized: a foreign-run message on the conductor stream stops the run
    s = system(api)
    s.run.bus.publish({**api.envelope("task.result", "lead:dba", "conductor", "dge_role", {"task_id": "x", "result": {}}, "autonomous:other"),
                       "when": {"created_at": "2029-01-01T00:00:00+00:00", "deadline": None, "after": []}})
    result, _ = cycle(s)
    out["foreign_message_on_the_conductor_stream"] = {**result, "tables": tables(s), "foreign_task_created": get(s.svc.store, "tasks", "x") is not None}
    # M7 test_tampered_dba_report_or_snapshot_cannot_promote_even_with_an_accepted_operation (the review's decision is the seam)
    def tamper(api, name, edit_fn, **options):
        s = system(api, **options)
        original = s.executor.decide_one

        def seam(agent, expected=None):
            row = original(agent, expected)
            edit_fn(s)
            return row
        s.executor.decide_one = seam
        original_promote, seen = s.run._promote, {}

        def watch(*args, **kwargs):
            seen["before"] = snap(s.svc.store)
            return original_promote(*args, **kwargs)
        s.run._promote = watch
        result, _ = cycle(s)
        result["promotion_before"] = seen.get("before")
        result["promotion_buckets_unchanged"] = seen.get("before") is not None and all(
            seen["before"][b] == result["store"][b] for b in A.PROMOTION_BUCKETS)
        out[name] = {**result, "tables": tables(s), "operation_status": (result["outcome"].get("operation") or {}).get("status"),
                     "leaks_secret": SECRET in json.dumps(result, default=str)}

    def report_summary(s):
        dba = get(s.svc.store, "tasks", run_row(s)["report"]["task_id"])
        dba["result"]["summary"] = "everything is fine " + SECRET   # row edited after binding (fixture)
        put(s.svc.store, "tasks", dba["id"], dba)
    tamper(api, "tampered_dba_report", report_summary)
    tamper(api, "tampered_snapshot", lambda s: s.artifacts.corrupt(snapshot_ref(s)))
    tamper(api, "snapshot_artifact_missing", lambda s: s.artifacts.bodies.pop(snapshot_ref(s)[7:]))
    other = system(api).port.observe(CURRENT_STATE["records"], topic="another topic", run_id=RUN, base_revision=BASE, max_age_seconds=600)
    tamper(api, "snapshot_swapped_for_another_valid_one", lambda s: s.artifacts.by_ref.__setitem__(snapshot_ref(s), other))
    tamper(api, "snapshot_swapped_for_garbage", lambda s: s.artifacts.by_ref.__setitem__(snapshot_ref(s), {"records": []}))
    tamper(api, "dba_task_status_changed", lambda s: edit(s, "tasks", run_row(s)["report"]["task_id"], status="failed"))
    tamper(api, "dba_task_agent_changed", lambda s: edit(s, "tasks", run_row(s)["report"]["task_id"], agent="lead:improvement"))
    tamper(api, "dba_execution_ref_changed", lambda s: edit(s, "tasks", run_row(s)["report"]["task_id"],
                                                             result={**get(s.svc.store, "tasks", run_row(s)["report"]["task_id"])["result"],
                                                                     "execution_ref": "sha256:" + "2" * 64}))
    tamper(api, "dba_reservation_unsettled", lambda s: edit(s, "invocation_reservations", "res-" + run_row(s)["report"]["task_id"], status="open"))
    tamper(api, "dba_reservation_of_another_record", lambda s: edit(s, "invocation_reservations", "res-" + run_row(s)["report"]["task_id"],
                                                                    task_id="someone-else"))
    tamper(api, "tamper_none_promotes", lambda s: None)
    # M7: the worker/reviewer gates are unchanged next to the council recheck
    result, s = case(api, evidence="verdict", verdict=False)
    out["worker_reviewer_gates_unchanged"] = {**result, "tables": tables(s)}
    # `_recheck` called directly over a finished run (LABELLED): the frozen values come from the run row, the store is read inside a transaction
    f, manifest, receipt = finished(api)
    row, observed, frozen = run_row(f), observed_of(f, manifest), run_row(f)["report"]
    claim_ids = {"c1"}

    def recheck(s=f, row=row, observed=observed, frozen=frozen, claim_ids=claim_ids, manifest=manifest):
        before = snap(s.svc.store)
        try:
            with s.svc.store.transaction() as tx:
                value = s.run._recheck(tx, manifest, row, observed, frozen, claim_ids)
            result = {"refs_keys": sorted(value["refs"]), "evidence_keys": sorted(value["evidence"]), "digest": canonical_digest(value),
                      "version": value["refs"]["version"], "dba": sorted(value["refs"]["dba"]), "snapshot": sorted(value["refs"]["snapshot"]),
                      "report": value["refs"]["report"] == {"sha256": frozen["sha256"], "snapshot_digest": frozen["snapshot_digest"]},
                      "topology_is_the_row": value["refs"]["topology"] == row["topology"],
                      "evidence": {k: (v if k != "dba_reservation_id" else v[:4]) for k, v in value["evidence"].items()}}
        except Exception as exc:   # the refusal is the characterized result
            result = {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc)[:200]}
        return {**result, "store_unchanged": snap(s.svc.store) == before}
    out["recheck_the_frozen_state"] = recheck()
    out["recheck_report_digest_differs"] = recheck(frozen={**frozen, "sha256": "0" * 64})
    out["recheck_execution_ref_differs"] = recheck(frozen={**frozen, "execution_ref": "sha256:" + "3" * 64})
    out["recheck_input_ref_differs"] = recheck(frozen={**frozen, "input_ref": "sha256:" + "4" * 64})
    out["recheck_other_task"] = recheck(frozen={**frozen, "task_id": "ghost-task"})
    out["recheck_other_snapshot_digest"] = recheck(observed={**observed, "sha256": "0" * 64})
    out["recheck_other_claims"] = recheck(claim_ids={"c9"})
    out["recheck_other_run"] = recheck(row={**row, "id": "council-002"})
    out["recheck_other_correlation"] = recheck(row={**row, "correlation_id": "autonomous:other"})
    out["recheck_other_base"] = recheck(manifest={**manifest, "base_revision": "e" * 40})
    out["recheck_other_topic"] = recheck(manifest={**manifest, "research": {**manifest["research"], "topic": "another topic"}})
    out["recheck_other_selection"] = recheck(observed={**observed, "selection": observed["selection"][:2]})
    out["recheck_missing_ref"] = recheck(observed={**observed, "ref": "sha256:" + "5" * 64})
    out["recheck_ignores_age"] = {**{"at": LATE}, "after_the_clock_passed": None}
    f.clock.now = LATE
    out["recheck_ignores_age"]["after_the_clock_passed"] = recheck()["refs_keys"] if "refused" not in recheck() else recheck()
    f.clock.now = START
    return out


# ---- c5 --------------------------------------------------------------------------------------------------------------------
def c5_bounds(api, ws):
    out = {}
    # M7 test_deadline_and_start_cap_bound_the_council_and_rejected_review_never_promotes
    s = system(api)
    out["deadline_expired_before_any_start"] = {**refused(s.svc.store, s.run.run, valid(api, deadline="2000-01-01T00:00:00+00:00"), IDENTITY,
                                                          BOUND_GOAL), "executor_calls": list(s.executor.calls), "port_calls": s.port.calls}
    for after_n in (1, 2, 3, 4, 5, 6):
        s = system(api, budget=O.FakeBudget(refuse_after=after_n))
        result, _ = cycle(s)
        out["start_cap_after_%d" % after_n] = {**result, "tables": tables(s)}
    result, s = case(api, verdict=False)
    out["rejected_review_never_promotes"] = {**result, "tables": tables(s), "promotion_row": get(s.svc.store, "promotions", RUN)}
    s = system(api)
    s.run.claim(valid(api), IDENTITY, BOUND_GOAL)
    other = api.CouncilRun(s.svc, s.executor, O.Bus(), api.Workflow(s.svc.store, s.svc.org), O.FakeBudget(), O.Collector())
    out["running_residue_without_takeover"] = {**refused(s.svc.store, other.run, valid(api), IDENTITY, BOUND_GOAL), "executor_calls": list(s.executor.calls)}
    result, s = case(api, worker="failed")
    out["worker_failed_no_promotion"] = {**result, "tables": tables(s)}
    # the deadline at every clock read of the council cycle (each read is a `_check_deadline`, a transition, a claim, a guard or an operation check)
    s = system(api)
    probe, _ = cycle(s)
    total = s.clock.reads
    sweep = {}
    for reads in range(1, total + 1):
        s = system(api)
        s.clock.flip = (reads, LATE)
        result, _ = cycle(s)
        sweep["after_%02d_reads" % reads] = {**brief(result), "reads_total": s.clock.reads}
    out["deadline_flip_sweep"] = {"reads_of_a_normal_cycle": total, "normal": brief(probe), "cases": sweep}
    # `_observe` checks the absolute deadline before the port is asked (a LABELLED direct call over a claimed run)
    s = system(api)
    claimed = s.run.claim(valid(api), IDENTITY, BOUND_GOAL)
    s.clock.now = LATE
    out["observe_deadline_expired_before_the_port"] = {**refused(s.svc.store, s.run._observe, valid(api), claimed["row"]), "port_calls": s.port.calls,
                                                       "puts": s.snapshots.puts}
    # the clock passes the deadline after the review (M7 style) and between the conductor and the worker
    clock = A.Clock()
    clock.after_review = LATE
    result, s = case(api, clock=clock)
    out["after_the_review"] = {**result, "tables": tables(s)}
    s = system(api)
    slow(s, "conductor", LATE)
    result, _ = cycle(s)
    out["between_the_conductor_and_the_worker"] = {**result, "tables": tables(s)}
    # M7 test_only_the_conductor_arbitration_self_loop_is_authorized (the organization's rules: bootstrap, another family)
    org = api.organization()
    allowed = {
        "conductor_assign_to_itself": api.envelope("task.assign", "conductor", "conductor", "dge_role", {"role": "conductor"}, "c"),
        "conductor_result_to_itself": api.envelope("task.result", "conductor", "conductor", "dge_role", {"task_id": "t", "result": {}}, "c"),
        "dba_result_to_the_conductor": api.envelope("task.result", "lead:dba", "conductor", "dge_role", {"task_id": "t", "result": {}}, "c"),
        "conductor_assign_the_dba": api.envelope("task.assign", "conductor", "lead:dba", "dge_role", {"role": "dba"}, "c")}
    denied = {
        "conductor_self_arbiter_role": api.envelope("task.assign", "conductor", "conductor", "dge_role", {"role": "arbiter"}, "c"),
        "conductor_self_plan": api.envelope("task.assign", "conductor", "conductor", "plan", {"role": "conductor"}, "c"),
        "improvement_self_conductor": api.envelope("task.assign", "lead:improvement", "lead:improvement", "dge_role", {"role": "conductor"}, "c"),
        "worker_self_implement": api.envelope("task.assign", "worker:implementation", "worker:implementation", "implement", {}, "c"),
        "dba_assign_improvement": api.envelope("task.assign", "lead:dba", "lead:improvement", "dge_role", {"role": "improvement_lead"}, "c"),
        "dba_result_to_improvement": api.envelope("task.result", "lead:dba", "lead:improvement", "dge_role", {"task_id": "t", "result": {}}, "c"),
        "conductor_self_result_implement": api.envelope("task.result", "conductor", "conductor", "implement", {"task_id": "t", "result": {}}, "c"),
        "review_result_to_the_conductor": api.envelope("review.result", "worker:implementation", "conductor", "review", {}, "c")}
    out["organization"] = {name: attempt(org.authorize, message) for name, message in {**allowed, **denied}.items()}
    return out


# ---- c6 --------------------------------------------------------------------------------------------------------------------
def c6_normal(api, ws):
    out = {}
    s = system(api)
    before = snap(s.svc.store)
    receipt = s.run.run(valid(api), IDENTITY, BOUND_GOAL)
    out["normal"] = {"receipt": view(receipt), "calls": list(s.executor.calls), "calls_are_the_council_order": s.executor.calls == ORDER,
                     "reserved": [[b["provider"], b["model"], b["purpose"]] for b in s.budget.reserved], "settled": len(s.budget.settled),
                     "port_calls": s.port.calls, "puts": s.snapshots.puts, "before": before, "after": snap(s.svc.store)}
    receipt_roles = {r: b["agent"] for r, b in receipt["roles"].items()}
    out["normal"]["roles"] = receipt_roles
    out["normal"]["durations"] = sorted(receipt["durations"])
    out["normal"]["topology"] = sorted(receipt["topology"]["roles"])
    snapshot, report = receipt["snapshot"], receipt["report"]
    with s.svc.store.transaction() as tx:
        tasks = {t["agent"]: t for t in tx.scan("tasks") if t["message"]["what"]["action"] == "dge_role"}
        details = {}
        for agent in ("lead:research", "lead:improvement", "conductor"):
            d = tasks[agent]["message"]["what"]["details"]
            details[agent] = {"identities": [d["snapshot_digest"], d["report_digest"]] == [snapshot["sha256"], report["sha256"]],
                              "report_summary": d["dba_report"]["summary"] == DBA_REPORT["summary"], "relay_via": d["relay"]["via"],
                              "keys": sorted(d)}
        conductor = tasks["conductor"]
        events = {e["role"]: e for e in tx.scan("dge_events")}
        design = tx.get("knowledge_nodes", "verified:council-001:design")["body"]
        promotion = tx.get("promotions", RUN)
        out["normal"]["store"] = {
            "role_details": details, "conductor_who": conductor["message"]["who"],
            "conductor_sees_the_alternative": [conductor["message"]["what"]["details"]["improvement_proposal"]["decision"],
                                               conductor["message"]["what"]["details"]["improvement_proposal"]["transition"]["rollback"]],
            "events": sorted(events), "attacker_payload": sorted(events["attacker"]["event"]["payload"]),
            "bound_agents": [events["attacker"]["binding"]["agent"], events["arbiter"]["binding"]["agent"]],
            "design_council": {"dba_task": design["council"]["dba"]["task_id"] == report["task_id"],
                               "snapshot": design["council"]["snapshot"]["sha256"] == snapshot["sha256"],
                               "report": design["council"]["report"]["sha256"] == report["sha256"],
                               "dba_agent": design["council"]["topology"]["roles"]["dba"]["agent"], "keys": sorted(design["council"])},
            "promotion_evidence": {"snapshot": promotion["evidence"]["snapshot_sha256"] == snapshot["sha256"],
                                   "dba_reservation": promotion["evidence"]["dba_reservation_id"] == "res-" + report["task_id"],
                                   "keys": sorted(promotion["evidence"])},
            "inbox_rows": len(tx.scan("workflow_inbox")), "envelope_record_state": s.artifacts.document(snapshot["ref"])["records"][1]["state"],
            "run_row": {k: v for k, v in tx.get("autonomous_runs", RUN).items() if k in ("status", "stage", "reason_code", "topology")}
                      | {"history": [[h["from"], h["to"]] for h in tx.get("autonomous_runs", RUN)["history"]],
                         "snapshot_keys": sorted(tx.get("autonomous_runs", RUN)["snapshot"]), "report_keys": sorted(tx.get("autonomous_runs", RUN)["report"])}}
    status = api.AutonomousRun(s.svc).status(RUN)
    out["status"] = {"view": A.receipt_view(status), "keys": sorted(status), "authority": status["authority"]}
    out["no_leaks"] = {"receipt_and_status_leak_secret_or_canary": SECRET in json.dumps(receipt) + json.dumps(status) or CANARY in json.dumps(receipt) + json.dumps(status)}
    # M7 test_dba_task_details_carry_the_redacted_snapshot_only
    with s.svc.store.transaction() as tx:
        dba = [t for t in tx.scan("tasks") if t["agent"] == "lead:dba"][0]
        d = dba["message"]["what"]["details"]
        out["dba_task_details"] = {"first_record_fields": d["snapshot"]["records"][0]["fields"], "leaks_secret": SECRET in api.canonical(d),
                                   "input_ref_is_the_frozen_one": A.evidence_ref_of(api, d) == tx.get("autonomous_runs", RUN)["report"]["input_ref"],
                                   "packet_claim": A.RESEARCH["claims"][0]["id"] in d["packet"]["claims"][0]["id"], "keys": sorted(d),
                                   "snapshot_digest_equals_the_frozen": d["snapshot_digest"] == snapshot["sha256"]}
    # the cached replay (a new run object over the same store: nothing executes, no second observation)
    before = snap(s.svc.store)
    replay = system(api)
    replay.run.service = s.svc
    cached = replay.run.run(valid(api), IDENTITY, BOUND_GOAL)
    out["replay_cached"] = {"cached": cached["cached"], "starts_equal": cached["starts"] == receipt["starts"], "port_calls": s.port.calls,
                            "replay_port_calls": replay.port.calls, "executor_calls": list(replay.executor.calls),
                            "unchanged": snap(s.svc.store) == before, "view": view(cached)}
    out["configuration_mismatch"] = refused(s.svc.store, s.run.run, valid(api), {**IDENTITY, "runtime": "other"}, BOUND_GOAL)
    out["configuration_mismatch_goal"] = refused(s.svc.store, s.run.run, valid(api), IDENTITY, {**BOUND_GOAL, "bytes": 4})
    out["configuration_mismatch_state"] = refused(s.svc.store, s.run.run, valid(api, current_state={**CURRENT_STATE, "max_age_seconds": 601}),
                                                   IDENTITY, BOUND_GOAL)
    # the observer: the snapshot stage's events (`_log`) next to the operation's
    o = system(api, observer=A.Observer())
    result, _ = cycle(o)
    out["observer"] = {"outcome": result["outcome"]["status"], "snapshot_events": [[e[0], e[1], e[2]] for e in o.observer.events
                                                       if e[2].get("attributes", {}).get("stage") == "snapshot"],
                       "kinds": sorted({e[0] for e in o.observer.events})}
    o = system(api, observer=A.Observer(), snapshot_mode="unavailable")
    result, _ = cycle(o)
    out["observer_refused"] = {"outcome": result["outcome"].get("reason_code"), "kinds": sorted({e[0] for e in o.observer.events}),
                               "snapshot_events": [[e[0], e[1], e[2]] for e in o.observer.events
                                                  if e[2].get("attributes", {}).get("stage") == "snapshot"]}
    # the clock of the run is also the port's: the snapshot is observed at the run's own instant
    out["observed_at_is_the_run_clock"] = {"observed_at": snapshot["observed_at"], "expires_at": snapshot["expires_at"],
                                           "expiry_is_observed_plus_max_age": snapshot["expires_at"] == EXPIRY}
    out["receipt_keys"] = sorted(receipt)
    return out


# ---- coverage --------------------------------------------------------------------------------------------------------------
RAISES = {   # application/council.py @ e38aa722: 19 raise statements (the branch-table lines) plus the `require` of `_pipeline`
    "99 require(...) (_pipeline: a v2 run needs a snapshot port and an artifact store)": [
        "c1_manifest.v2_no_snapshot_port", "c1_manifest.v2_no_artifact_store", "c1_manifest.v2_neither"],
    "124 report_invalid (_pipeline: the DBA answer is not a report)": [
        "c3_roles.dba_foreign_snapshot_digest", "c3_roles.dba_summary_too_long", "c3_roles.dba_unknowns_too_long", "c3_roles.dba_unknowns_not_a_list",
        "c3_roles.dba_unknown_claim", "c3_roles.dba_extra_field"],
    "160 AutonomousRefused(exc.reason_code) from CouncilInputOverflow (_pipeline: research and improvement proposals)": [
        "c3_roles.overflow_research_proposal", "c3_roles.overflow_improvement_proposal", "c3_roles.overflow_improvement_findings"],
    "164 AutonomousRefused(exc.reason_code) from CouncilFieldRefused (_pipeline: the fixed council_field_invalid code)": [
        "c3_roles.oversized_improvement_summary", "c3_roles.improvement_summary_empty", "c3_roles.improvement_summary_type",
        "c3_roles.improvement_rationale_too_long", "c3_roles.improvement_transition_rollback_too_long",
        "c3_roles.improvement_transition_retirement_empty"],
    "166 debate_refused:<DgeRefused code> (_pipeline)": ["c3_roles.debate_refused_session_version", "c3_roles.debate_refused_session_terminal", "c3_roles.debate_refused_session_packet_digest",
                                                         "c3_roles.debate_refused_session_round", "c3_roles.debate_refused_session_role_out_of_order", "c3_roles.debate_refused_session_expired",
                                                         "c3_roles.debate_refused_session_owner"],
    "169 role_session_shared / council_identity_mismatch / debate_refused:<ContractError type> (_pipeline)": [
        "c3_roles.role_session_shared", "c3_roles.swapped_report_identity", "c3_roles.unknown_claim_research_lead", "c3_roles.unknown_claim_improvement_lead",
        "c3_roles.bad_claim_ids_duplicate", "c3_roles.improvement_decision_unknown", "c3_roles.debate_refused_unsupported_critical"],
    "190 AutonomousRefused(exc.reason_code) from CouncilInputOverflow (_admit: the frozen packet and the DBA report)": [
        "c3_roles.overflow_packet", "c3_roles.overflow_dba_report", "c3_roles.admit_direct"],
    "199-207 _role: the consumer overflow lifted from the task error, only in its safe shape": [
        "c3_roles.consumer_retry_host_overhead",
        "c3_roles.consumer_failed_required",
        "c3_roles.consumer_lifted_for_the_dba"],
    "201 bare re-raise (_role: a refusal that is not role_failed/role_retry)": ["c3_roles.debate_refused_conductor_verdict", "c4_relay_recheck.missing_role_artifact",
                                                                             "c4_relay_recheck.wrong_agent_role_task_unbound"],
    "206 bare re-raise (_role: a role_failed/role_retry task whose error is not the safe shape)": [
        "c3_roles.consumer_retry_other_type", "c3_roles.consumer_failed_no_error", "c3_roles.consumer_error_not_text",
        "c3_roles.role_failed_dba", "c3_roles.role_retry_research_lead"],
    "229 snapshot_unavailable / the fixed refusal codes (_observe: the port refused)": [
        "c2_snapshot.refused_unavailable", "c2_snapshot.refused_read_error", "c2_snapshot.refused_connect_error", "c2_snapshot.refused_malformed",
        "c2_snapshot.port_snapshot_stale", "c2_snapshot.port_snapshot_corrupt", "c2_snapshot.port_snapshot_mismatch", "c2_snapshot.port_unknown_code",
        "c2_snapshot.port_contract_error_without_code", "c2_snapshot.port_runtime_error", "c2_snapshot.observe_chain_raw"],
    "231 snapshot_mismatch (_observe: a valid envelope that is not the one asked for)": [
        "c2_snapshot.mismatch_other_topic", "c2_snapshot.mismatch_other_run", "c2_snapshot.mismatch_other_base", "c2_snapshot.mismatch_other_selection"],
    "249 snapshot_missing (_guard: the run row holds no matching snapshot)": ["c2_snapshot.guard_run_without_a_snapshot", "c2_snapshot.guard_recorded_digest_differs",
                                                                              "c2_snapshot.guard_recorded_ref_differs", "c2_snapshot.guard_recorded_expiry_differs"],
    "255 AutonomousRefused(SnapshotError code) (_guard: stale, mismatch, corrupt)": [
        "c2_snapshot.stale_at_the_first_guard", "c2_snapshot.stale_at_the_next_role_boundary", "c2_snapshot.stale_before_the_implementation",
        "c2_snapshot.swapped_valid_other_topic", "c2_snapshot.swapped_not_a_snapshot", "c2_snapshot.guard_stale_at_the_expiry",
        "c2_snapshot.guard_other_selection"],
    "264 snapshot_corrupt / snapshot_missing (_frozen_document: the evidence port's refusals)": [
        "c2_snapshot.frozen_document_evidence_corrupt", "c2_snapshot.frozen_document_evidence_invalid", "c2_snapshot.frozen_document_evidence_missing",
        "c2_snapshot.frozen_document_contract_error_without_code", "c2_snapshot.corrupt_after_dba", "c2_snapshot.missing_after_dba"],
    "266 snapshot_missing (_frozen_document: any other failure)": ["c2_snapshot.frozen_document_file_not_found", "c2_snapshot.frozen_document_os_error",
                                                                    "c2_snapshot.frozen_document_value_error", "c2_snapshot.frozen_document_runtime_error",
                                                                    "c2_snapshot.frozen_document_unknown_reference", "c2_snapshot.frozen_document_not_a_reference"],
    "277 report_not_relayed (_relay)": ["c4_relay_recheck.unrelayed_dba_report", "c4_relay_recheck.unrelayed_conductor_result",
                                        "c4_relay_recheck.relay_direct_empty_bus", "c4_relay_recheck.relay_direct_other_sender",
                                        "c4_relay_recheck.relay_direct_other_task", "c4_relay_recheck.relay_direct_other_action",
                                        "c4_relay_recheck.relay_direct_assign_not_result"],
    "290 ContractError('report_mismatch') (_recheck)": ["c4_relay_recheck.recheck_report_digest_differs", "c4_relay_recheck.recheck_execution_ref_differs"],
    "292 promotion_report_unproven:<code> (_recheck: the DBA binding, the artifact and the report)": [
        "c4_relay_recheck.tampered_dba_report", "c4_relay_recheck.dba_task_status_changed", "c4_relay_recheck.dba_task_agent_changed",
        "c4_relay_recheck.dba_execution_ref_changed", "c4_relay_recheck.dba_reservation_unsettled",
        "c4_relay_recheck.dba_reservation_of_another_record", "c4_relay_recheck.recheck_other_task", "c4_relay_recheck.recheck_other_claims",
        "c4_relay_recheck.recheck_input_ref_differs", "c4_relay_recheck.recheck_other_snapshot_digest"],
    "298 promotion_snapshot_unproven:<code> (_recheck: the frozen snapshot)": [
        "c4_relay_recheck.tampered_snapshot", "c4_relay_recheck.snapshot_artifact_missing", "c4_relay_recheck.snapshot_swapped_for_another_valid_one",
        "c4_relay_recheck.snapshot_swapped_for_garbage", "c4_relay_recheck.recheck_missing_ref", "c4_relay_recheck.recheck_other_selection",
        "c4_relay_recheck.recheck_other_topic", "c4_relay_recheck.recheck_other_base"]}
EXCEPTS = {   # the `except` clauses of the branch-table section, each with the cases that enter it
    "123 ContractError (_pipeline: the DBA answer is not a report)": RAISES["124 report_invalid (_pipeline: the DBA answer is not a report)"],
    "159 CouncilInputOverflow (_pipeline: a lead proposal over its allowance)": ["c3_roles.overflow_research_proposal", "c3_roles.overflow_improvement_proposal"],
    "161 CouncilFieldRefused (_pipeline: the fixed field code)": ["c3_roles.oversized_improvement_summary", "c3_roles.improvement_rationale_too_long"],
    "165 DgeRefused (_pipeline: sessions.submit refused)": ["c3_roles.debate_refused_session_version", "c3_roles.debate_refused_session_owner"],
    "167 ContractError (_pipeline: a lead output refused)": ["c3_roles.role_session_shared", "c3_roles.swapped_report_identity",
                                                            "c3_roles.unknown_claim_research_lead"],
    "189 CouncilInputOverflow (_admit)": ["c3_roles.overflow_packet", "c3_roles.admit_direct"],
    "199 AutonomousRefused (_role: the consumer-gate refusal or any other role refusal)": ["c3_roles.consumer_retry_host_overhead",
                                                                                           "c3_roles.consumer_retry_other_type", "c4_relay_recheck.missing_role_artifact"],
    "222 ContractError (_observe: the port's own refusal)": ["c2_snapshot.refused_unavailable", "c2_snapshot.refused_malformed",
                                                              "c2_snapshot.port_snapshot_stale", "c2_snapshot.port_contract_error_without_code"],
    "224 Exception (_observe: anything else is not an observation)": ["c2_snapshot.observe_chain_raw", "c2_snapshot.port_runtime_error",
                                                                      "c2_snapshot.port_value_error"],
    "254 SnapshotError (_guard)": ["c2_snapshot.stale_at_the_next_role_boundary", "c2_snapshot.swapped_valid_other_topic", "c2_snapshot.swapped_not_a_snapshot"],
    "262 ContractError (_frozen_document)": ["c2_snapshot.frozen_document_evidence_corrupt", "c2_snapshot.frozen_document_contract_error_without_code"],
    "265 Exception (_frozen_document)": ["c2_snapshot.frozen_document_os_error", "c2_snapshot.frozen_document_runtime_error"],
    "291 ContractError (_recheck: the DBA binding, artifact or report)": ["c4_relay_recheck.tampered_dba_report", "c4_relay_recheck.recheck_report_digest_differs"],
    "297 (AutonomousRefused, SnapshotError) (_recheck: the frozen snapshot)": ["c4_relay_recheck.tampered_snapshot", "c4_relay_recheck.snapshot_artifact_missing"]}
M7_TESTS = {   # tests/test_council.py @ e38aa722 (a ParametrizeS count as their cases), then tests/test_council_input.py's run-level gates
    "test_v2_manifest_keeps_the_v1_canonical_form_and_refuses_bad_current_state_before_any_provider": [
        "c1_manifest.v2_canonical_form", "c1_manifest.refused_empty", "c1_manifest.refused_too_many", "c1_manifest.refused_duplicate",
        "c1_manifest.refused_unknown_bucket", "c1_manifest.refused_unsafe_id", "c1_manifest.refused_extra_field", "c1_manifest.refused_age_bool",
        "c1_manifest.refused_age_low", "c1_manifest.refused_age_high", "c1_manifest.refused_age_text", "c1_manifest.refused_record_text",
        "c1_manifest.v1_validator_never_admits_v2", "c1_manifest.refused_before_any_provider"],
    "test_snapshot_reduces_rows_to_digests_and_whitelist_and_keeps_missing_unknown_and_found_apart": [],
    "test_status_fields_are_finite_vocabularies_and_known_actor_syntax_never_arbitrary_tokens": [],
    "test_application_snapshot_refusal_keeps_no_raw_exception_chain": [
        "c2_snapshot.observe_chain_connect_error", "c2_snapshot.observe_chain_read_error", "c2_snapshot.observe_chain_unavailable",
        "c2_snapshot.observe_chain_raw"],
    "test_critical_improvement_finding_is_converted_once_and_reaches_the_event_and_the_conductor_intact": ["c3_roles.critical_converted_once"],
    "test_unknown_claim_id_in_a_lead_contribution_is_refused_before_the_next_role[research_lead-3]": ["c3_roles.unknown_claim_research_lead"],
    "test_unknown_claim_id_in_a_lead_contribution_is_refused_before_the_next_role[improvement_lead-4]": ["c3_roles.unknown_claim_improvement_lead"],
    "test_an_oversized_improvement_summary_stops_with_the_fixed_field_code_and_keeps_the_output": ["c3_roles.oversized_improvement_summary"],
    "test_normal_council_cycle_uses_real_agents_shares_one_report_reaches_the_conductor_and_promotes": [
        "c6_normal.normal", "c6_normal.status", "c6_normal.no_leaks", "c6_normal.replay_cached"],
    "test_v1_manifest_through_the_council_class_runs_the_v1_flow_with_six_starts_and_no_snapshot": ["c1_manifest.v1_manifest_runs_the_v1_flow"],
    "test_unavailable_or_malformed_snapshot_refuses_after_research_with_no_further_start[unavailable-snapshot_unavailable]": ["c2_snapshot.refused_unavailable"],
    "test_unavailable_or_malformed_snapshot_refuses_after_research_with_no_further_start[read_error-snapshot_unavailable]": ["c2_snapshot.refused_read_error"],
    "test_unavailable_or_malformed_snapshot_refuses_after_research_with_no_further_start[connect_error-snapshot_unavailable]": ["c2_snapshot.refused_connect_error"],
    "test_unavailable_or_malformed_snapshot_refuses_after_research_with_no_further_start[malformed-snapshot_corrupt]": ["c2_snapshot.refused_malformed"],
    "test_stale_snapshot_stops_at_the_next_role_boundary_without_refresh_or_extra_start": ["c2_snapshot.stale_at_the_next_role_boundary"],
    "test_corrupt_or_missing_frozen_snapshot_and_swapped_report_identity_refuse_before_the_next_role": [
        "c2_snapshot.corrupt_after_dba", "c2_snapshot.missing_after_dba", "c3_roles.swapped_report_identity", "c3_roles.dba_foreign_snapshot_digest",
        "c3_roles.role_session_shared"],
    "test_unrelayed_dba_report_wrong_agent_and_missing_role_artifact_stop_the_run": [
        "c4_relay_recheck.unrelayed_dba_report", "c4_relay_recheck.wrong_agent_role_task_unbound", "c4_relay_recheck.missing_role_artifact"],
    "test_deadline_and_start_cap_bound_the_council_and_rejected_review_never_promotes": [
        "c5_bounds.deadline_expired_before_any_start", "c5_bounds.start_cap_after_6", "c5_bounds.rejected_review_never_promotes",
        "c5_bounds.running_residue_without_takeover"],
    "test_tampered_dba_report_or_snapshot_cannot_promote_even_with_an_accepted_operation": [
        "c4_relay_recheck.tampered_dba_report", "c4_relay_recheck.tampered_snapshot", "c4_relay_recheck.worker_reviewer_gates_unchanged"],
    "test_only_the_conductor_arbitration_self_loop_is_authorized": ["c5_bounds.organization", "c4_relay_recheck.foreign_message_on_the_conductor_stream"],
    "test_dba_task_details_carry_the_redacted_snapshot_only": ["c6_normal.dba_task_details"],
    "tests/test_council_input.py::test_oversized_packet_ends_the_run_before_the_snapshot_or_the_dba_and_keeps_the_researcher_evidence": ["c3_roles.overflow_packet"],
    "tests/test_council_input.py::test_oversized_unicode_dba_report_after_a_large_packet_stops_before_the_relay_and_either_lead": ["c3_roles.overflow_dba_report"],
    "tests/test_council_input.py::test_oversized_research_lead_proposal_after_a_large_packet_stops_before_submit_and_the_improvement_lead": [
        "c3_roles.overflow_research_proposal"],
    "tests/test_council_input.py::test_oversized_improvement_proposal_including_findings_stops_before_the_conductor_with_findings_retained": [
        "c3_roles.overflow_improvement_proposal", "c3_roles.overflow_improvement_findings"],
    "tests/test_council_input.py::test_earlier_unused_capacity_lets_a_report_and_findings_over_the_retired_ceilings_reach_promotion": [
        "c3_roles.control_over_the_retired_ceilings_promotes"],
    "tests/test_council_input.py::test_consumer_gate_refusal_reaches_the_run_as_the_precise_reason_only_in_its_safe_shape": [
        "c3_roles.consumer_retry_host_overhead",
        "c3_roles.consumer_failed_other_type"]}
OTHER_FAMILY = {   # M7 tests whose subject is another module (listed, not mirrored here)
    "test_snapshot_reduces_rows_to_digests_and_whitelist_and_keeps_missing_unknown_and_found_apart": "other family: domain.council (the snapshot "
        "reducer, `check_snapshot`, `report_from_dba`) and adapters.council_snapshot (`ReadOnlySnapshot`): the port is used here only as a double",
    "test_status_fields_are_finite_vocabularies_and_known_actor_syntax_never_arbitrary_tokens": "other family: domain.council (`snapshot_records`, "
        "`validate_snapshot`, the status vocabularies)",
    "tests/test_council_input.py (the policy, allowance, prefix, delivery, required and executor-gate tests)": "other family: domain.council_input and "
        "the executor/delivery adapters; only the CouncilRun gates above are this module's",
    "tests/test_council_roles.py": "other family: adapters.autonomous_roles and domain.council (the role schemas and bounded fields)",
    "tests/test_council_delivery.py": "other family: the council delivery projection",
    "tests/test_council_postgres.py": "other family: adapters.council_snapshot against a real PostgreSQL (the integration lane)"}


def resolve(result, path):
    node = result
    for part in path.split("."):
        node = node[part]   # a pointer that does not resolve is a driver error, never a silent gap
        # (a key may itself contain a dot or a colon only where the case name says so: such names use no dots)
    return node


def coverage(result) -> dict:
    for table in (RAISES, EXCEPTS, M7_TESTS):
        for pointers in table.values():
            for pointer in pointers:
                resolve(result, pointer)
    unreachable = sorted(p for pointers in list(RAISES.values()) + list(EXCEPTS.values()) + list(M7_TESTS.values()) for p in pointers
                         if isinstance(resolve(result, p), dict) and "unreachable" in resolve(result, p))
    return {"raises": dict(RAISES), "excepts": dict(EXCEPTS), "m7_tests": dict(M7_TESTS), "other_family": dict(OTHER_FAMILY),
            "unreachable": {p: resolve(result, p)["unreachable"] for p in unreachable},
            "counts": {"raise_statements_in_branch_table": 19, "raise_entries": len(RAISES), "except_entries": len(EXCEPTS), "m7_test_node_ids": len(M7_TESTS),
                       "m7_tests_other_family": len(OTHER_FAMILY)}}


GROUPS = (("c1_manifest", c1_manifest), ("c2_snapshot", c2_snapshot), ("c3_roles", c3_roles), ("c4_relay_recheck", c4_relay_recheck),
          ("c5_bounds", c5_bounds), ("c6_normal", c6_normal))


def run(api) -> dict:
    ws = R.Workspace()
    try:
        result, counts = {}, {}
        for name, group in GROUPS:
            result[name] = ws.scrub(group(api, ws))
            counts[name] = len(result[name])
        result["cases_per_group"] = counts
        result["coverage"] = coverage(result)
        return result
    finally:
        ws.close()

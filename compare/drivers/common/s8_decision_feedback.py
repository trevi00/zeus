"""Shared S8 scenario steps (`research.decision_feedback`): M7 `application/decision_feedback.py` (`DecisionFeedback`: `collect`, `status`, `report`),
characterized BEFORE the module moves into RESEARCH (S8 batch B4, DESIGN-s8 §21 V25: R-df1 the two coordination bucket names as V9 constants, R-df2 the
five own buckets). The golden is placement-neutral: it observes SOURCE behaviour only.

Each case is labelled with the M7 test it mirrors (`m7_test`), or `none`. M7's `tests/test_decision_feedback.py` (18 tests) produces its runs with the
REAL `CouncilRun`/`AutonomousRun` state machines over a `Harness`; this golden PLANTS the rows those machines leave (`autonomous_runs`, `dge_sessions`,
`dge_events`, `tasks`, `invocation_reservations`) in their stored shapes, because the run machinery is other families' code (research.autonomous,
research.council, research.dge, coordination). Left out, reported in `m7_tests`:
- `test_postgres_collection_is_idempotent_across_restarts` (integration; a disposable PostgreSQL), carried to the units/.pg step;
- `test_distinct_run_membership_is_exact_past_the_window_and_bounded_at_the_durable_cap` is recorded here over the domain functions, as are the three
  other pure-contract tests (registry, matching, outcome states): they are `domain.decision_feedback`, already moved, and are recorded so the whole
  test file is mirrored.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. LABELLED doubles (nothing here is an actual Codex, council or model run):
- the rows above, planted by `seed_run`: a council topology (version 2, conductor in the arbiter slot), an executor-bound session and decision event, a
  succeeded task whose result is the artifact's answer, a settled accepted reservation, and the artifact the evidence port returns;
- `Evidence`: the `document(ref)` port over a dict, with scripted faults (`evidence_missing`/`evidence_corrupt`/`evidence_invalid` as `ContractError`
  subclasses with a `reason_code`, and a generic `OSError` of a port without fixed codes), recording every ref read;
- `Tick`: the scripted clock, a callable that advances one millisecond per call (it is passed as `clock`; nothing patches time);
- `Interleaved`, `BrokenStore`, `BrokenScan`: M7's fault stores (a second collector between the read and the record transaction; an unreachable store;
  a connection that breaks part-way through the page).
The whole-store digest (16 hex) is recorded before and after every refusal, with a `wrote` flag; the digest of every row outside this collector's own
buckets is compared around the successful collections.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import threading
from datetime import datetime, timedelta, timezone

REPOSITORY = "r"
BASE = "a" * 40
REVISION, OTHER_REVISION = "1" * 40, "2" * 40
REGISTRY_SHA = "3" * 64
REGISTRY_PATH = "docs/zeus/procedures.json"
CANARY = "CANARY-must-never-be-emitted"
PATHS = ["docs/zeus/operations/autonomous-dge-001/RUNBOOK.md"]
CRITERIA = ["focused tests pass"]
PLAN = {"objective": "Add the RUNBOOK note " + CANARY, "acceptance_criteria": list(CRITERIA), "allowed_paths": list(PATHS)}
OTHER_PLAN = {"objective": "Add the other RUNBOOK note " + CANARY, "acceptance_criteria": list(CRITERIA),
              "allowed_paths": ["docs/zeus/operations/other-001/RUNBOOK.md"]}
T0 = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)

M7_TESTS = {
    "covered": ["test_registry_pins_exact_contracts_and_refuses_malformed_entries_without_echoing_values (the domain function, recorded here)",
                "test_matching_is_exact_and_missing_or_ambiguous_entries_stay_unknown (the domain function)",
                "test_outcome_states_preserve_the_source_status_and_terminal_accepted_is_not_correctness (the domain function)",
                "test_two_distinct_council_runs_make_one_candidate_and_repeated_collection_is_idempotent (planted rows)",
                "test_distinct_run_membership_is_exact_past_the_window_and_bounded_at_the_durable_cap (the domain functions)",
                "test_a_group_past_the_reported_window_keeps_exact_distinct_membership_across_collections (the window bound narrowed to 2 on the "
                "domain module, as M7 does)",
                "test_one_run_a_different_contract_or_a_v1_source_never_groups_into_a_candidate (a planted run without the council topology)",
                "test_a_pending_outcome_joins_later_and_a_changed_terminal_history_is_a_conflict",
                "test_a_page_read_before_the_terminal_outcome_is_stale_and_not_a_changed_history (the Interleaved store)",
                "test_a_source_row_that_cannot_be_re_read_stays_unknown_and_writes_nothing",
                "test_an_unproven_decision_identity_refuses_evidence_credit (the six parametrizations)",
                "test_only_the_stored_execution_artifact_earns_evidence_credit_never_a_matching_reference (the three parametrizations)",
                "test_the_real_artifacts_of_the_same_two_runs_do_verify (and the missing evidence port)",
                "test_a_bounded_scan_reports_truncation_and_continues_from_the_cursor",
                "test_a_store_failure_is_unavailable_not_zero_samples",
                "test_concurrent_collectors_serialize_into_one_candidate_and_one_set_of_occurrences (final state only)",
                "test_status_and_report_expose_counts_limits_and_no_promotion_authority"],
    "left_out": {"test_postgres_collection_is_idempotent_across_restarts": "integration: a disposable PostgreSQL; carried to the units/.pg step",
                 "the real CouncilRun/AutonomousRun that produced M7's rows": "other families (research.autonomous, research.council, research.dge); "
                                                                              "the rows are planted in their stored shapes"}}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=repr).encode()).hexdigest()[:16]


def store_digest(store):
    with store.transaction() as tx:
        return sha([[r["bucket"], r["id"], sha(r["body"])] for r in tx.records()])


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


class Tick:
    """LABELLED scripted clock: a callable returning an ISO text that advances one millisecond per call."""

    def __init__(self):
        self.now = T0

    def __call__(self):
        self.now += timedelta(milliseconds=1)
        return self.now.isoformat()


class Evidence:
    """LABELLED execution-evidence port: `document(ref)` over a dict of artifacts, with scripted faults per ref."""

    def __init__(self, api):
        self.api, self.documents, self.faults, self.reads = api, {}, {}, []

        class Fault(api.ContractError):
            def __init__(self, code):
                super().__init__("evidence fault: " + code)
                self.reason_code = code

        self.Fault = Fault

    def document(self, ref):
        self.reads.append(ref)
        fault = self.faults.get(ref)
        if fault == "generic":
            raise OSError("artifact store unreachable (injected fault)")
        if fault:
            raise self.Fault(fault)
        if ref not in self.documents:
            raise self.Fault("evidence_missing")
        return self.documents[ref]


class World:
    def __init__(self, api):
        self.api = api
        self.store = api.MemoryStore()
        self.evidence = Evidence(api)
        self.clock = Tick()
        self.feedback = api.DecisionFeedback(self.store, self.clock, evidence=self.evidence)
        self.runs = {}

    # ----- planting ---------------------------------------------------------------------------------------------------------------------
    def seed_run(self, run_id, plan=None, repository=REPOSITORY, status="accepted", reason="promoted", council=True):
        """LABELLED: the rows a finished council run leaves (M7 gets them from `CouncilRun`)."""
        api, df = self.api, self.api.df
        plan = plan or PLAN
        session_id, task_id, reservation_id, event_id = "dge-" + run_id, "task-" + run_id, "res-" + run_id, "ev-" + run_id
        packet_digest = api.digest({"packet": run_id})
        answer = {"verdict": "accept", "rationale": "structure holds", "dispositions": [], "research_question": None, "run": run_id}
        details = {"stage": "dge:" + df.DECIDING_ROLE, "packet_digest": packet_digest}
        artifact = {"answer": answer, "invocation": {"reservation": reservation_id, "outcome": "accepted"},
                    "research_binding": {"stage": "dge:" + df.DECIDING_ROLE, "basis_revision": BASE, "evidence_ref": api.evidence_ref_for(details)},
                    "execution_assignment": {"provider": "labelled-provider"}, "thread_id": "thread-" + run_id}
        ref = "sha256:" + api.digest(artifact)
        self.evidence.documents[ref] = artifact
        binding = {"task_id": task_id, "execution_ref": ref, "agent": df.DECIDING_AGENT, "stage": "dge:" + df.DECIDING_ROLE,
                   "origin": df.ORIGIN_EXECUTOR, "generation": 1, "attempt": 1, "output_sha256": api.digest(answer)}
        topology = {"version": 2, "roles": {df.DECIDING_ROLE: {"agent": df.DECIDING_AGENT, "slot": df.DECISION_SLOT}}} if council \
            else {"version": 1, "roles": {}}
        put(self.store, api.RUNS, run_id, {
            "id": run_id, "identity": {"repository": repository, "runtime_policy": "policy-1", "provider": "labelled-provider",
                                       "evidence_profile": "profile-1"},
            "session_id": session_id, "packet_digest": packet_digest, "manifest_sha256": "4" * 64,
            "goal": {"path": "docs/zeus/goal.md", "sha256": "5" * 64}, "topology": topology,
            "roles": {df.DECIDING_ROLE: {"task_id": task_id, "execution_ref": ref, "output_sha256": binding["output_sha256"]}},
            "status": status, "reason_code": reason, "finished_at": None if status == "running" else "2026-09-22T11:00:00+00:00",
            "updated_at": "2026-09-22T11:00:00+00:00", "stage": "done", "operation": {"id": "op-" + run_id, "status": status, "reason_code": reason},
            "promotion": {"id": "promotion-" + run_id}})
        put(self.store, api.SESSIONS, session_id, {
            "id": session_id, "owner": run_id, "origin": df.ORIGIN_EXECUTOR, "packet_digest": packet_digest,
            "history": [{"role": df.DECISION_SLOT, "event_id": event_id}], "plan": plan, "base_revision": BASE, "state": "design_approved",
            "decision_event_id": event_id})
        put(self.store, api.EVENTS, session_id + ":" + event_id, {
            "id": session_id + ":" + event_id, "session_id": session_id, "role": df.DECISION_SLOT, "origin": df.ORIGIN_EXECUTOR,
            "event_id": event_id, "digest": api.digest({"event": event_id}), "round": 3, "recorded_at": "2026-09-22T10:30:00+00:00",
            "event": {"packet_digest": packet_digest, "payload": {"verdict": "accept", "dispositions": []}}, "binding": binding})
        put(self.store, api.TASKS, task_id, {
            "id": task_id, "status": "succeeded", "agent": df.DECIDING_AGENT, "generation": 1, "attempt": 1,
            "result": {**answer, "execution_ref": ref}, "message": {"what": {"details": details}}})
        put(self.store, api.RESERVATIONS, reservation_id, {
            "id": reservation_id, "bucket": api.TASKS, "task_id": task_id, "generation": 1, "attempt": 1, "stage": "dge:" + df.DECIDING_ROLE,
            "status": "settled", "outcome": "accepted", "invocation": "inv-" + run_id})
        self.runs[run_id] = {"session": session_id, "event": session_id + ":" + event_id, "task": task_id, "reservation": reservation_id, "ref": ref}
        return self.runs[run_id]

    def edit(self, bucket, key, **fields):
        """LABELLED row edit: the state another history or an injected fault would leave."""
        row = get(self.store, bucket, key)
        put(self.store, bucket, key, {**row, **fields})
        return row

    # ----- observing --------------------------------------------------------------------------------------------------------------------
    def rows(self, bucket):
        return scan(self.store, bucket)

    def snapshot(self):
        """The digest of every row outside this collector's own five buckets."""
        with self.store.transaction() as tx:
            return sha([[r["bucket"], r["id"], sha(r["body"])] for r in tx.records() if r["bucket"] not in self.api.WRITE_BUCKETS])

    def registry(self, *entries):
        return {"schema": "urn:zeus:procedure-registry:1", "version": 1, "entries": list(entries) if entries else [entry()]}

    def collect(self, feedback=None, **over):
        args = dict(registry=self.registry(), registry_revision=REVISION, registry_path=REGISTRY_PATH, registry_sha256=REGISTRY_SHA,
                    repository=REPOSITORY, limit=100, after="")
        args.update(over)
        return (feedback or self.feedback).collect(**args)

    def call(self, fn, *args, **kwargs):
        """One call: the whole-store digest before and after, the value or the refusal (type, reason code, message)."""
        before = store_digest(self.store)
        try:
            out = {"outcome": "returned", "value": fn(*args, **kwargs)}
        except BaseException as exc:  # noqa: BLE001 - what propagates is the observation
            out = {"outcome": "raised", "type": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc),
                   "is_contract_error": isinstance(exc, self.api.ContractError), "cause_type": None if exc.__cause__ is None else type(exc.__cause__).__name__}
        after = store_digest(self.store)
        return {**out, "store_before": before, "store_after": after, "wrote": before != after}


def entry(**overrides):
    document = {"id": "runbook-note", "source_kind": "council", "repository": REPOSITORY, "allowed_paths": list(PATHS),
                "acceptance_criteria_sha256": None, "remediation": "skill"}
    document.update(overrides)
    return document


def make_entry(api, **overrides):
    return entry(**{"acceptance_criteria_sha256": api.df.criteria_digest(CRITERIA), **overrides})


def world(api):
    w = World(api)
    w.registry = lambda *entries, w=w: {"schema": "urn:zeus:procedure-registry:1", "version": 1,
                                        "entries": list(entries) if entries else [make_entry(api)]}
    return w


class Interleaved:
    """M7's coordination fixture: runs `between` once, before the second transaction (the record transaction) opens."""

    def __init__(self, store, between):
        self.store, self.between, self.transactions = store, between, 0

    def transaction(self):
        self.transactions += 1
        if self.transactions == 2:
            self.between()
        return self.store.transaction()


class BrokenStore:
    """LABELLED injected fault: the control-plane store is unreachable."""

    def transaction(self):
        raise RuntimeError("store unavailable (injected fault)")


class BrokenScan:
    """LABELLED injected fault: the connection breaks part-way through the bounded page."""

    def transaction(self):
        class Tx:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            @staticmethod
            def entries(bucket, after="", limit=100):
                raise OSError("connection reset (injected fault)")
        return Tx()


def brief(receipt):
    """The parts of a receipt the cases compare by name; the whole receipt is recorded where it is the subject."""
    return {k: receipt[k] for k in ("counts", "reasons", "truncated", "next_cursor", "scan_limit", "after")}


# ----- steps -------------------------------------------------------------------------------------------------------------------------------
def a_surface(api):
    params = list(inspect.signature(api.DecisionFeedback.__init__).parameters.values())
    w = world(api)
    return {"surface": {
        "buckets": {"RUNS": api.RUNS, "RESERVATIONS": api.RESERVATIONS, "TASKS": api.TASKS, "SESSIONS": api.SESSIONS, "EVENTS": api.EVENTS,
                    "OBSERVATIONS": api.OBSERVATIONS, "GROUPS": api.GROUPS, "CANDIDATES": api.CANDIDATES, "CONFLICTS": api.CONFLICTS,
                    "COLLECTIONS": api.COLLECTIONS},
        "READ_BUCKETS": list(api.READ_BUCKETS), "WRITE_BUCKETS": list(api.WRITE_BUCKETS), "all": list(api.ALL),
        "constructor": [[p.name, p.kind.name, "<callable>" if callable(p.default) else repr(p.default)] for p in params],
        "methods": {n: str(inspect.signature(getattr(api.DecisionFeedback, n))) for n in ("collect", "status", "report")},
        "attributes": {"store": w.feedback.store is w.store, "clock": w.feedback.clock is w.clock, "evidence": w.feedback.evidence is w.evidence},
        "deciding": [api.df.DECIDING_ROLE, api.df.DECIDING_AGENT, api.df.DECISION_SLOT]}}


def b_pure(api):
    df, cases = api.df, {}

    def attempt(fn):
        try:
            return {"value": fn()}
        except Exception as exc:  # noqa: BLE001
            return {"raised": type(exc).__name__, "message": str(exc), "reason_code": getattr(exc, "reason_code", None),
                    "canary_echoed": CANARY in str(exc)}

    cases["registry_valid"] = attempt(lambda: df.validate_registry({"schema": "urn:zeus:procedure-registry:1", "version": 1,
                                                                    "entries": [make_entry(api)]}))
    valid = df.validate_registry({"schema": "urn:zeus:procedure-registry:1", "version": 1, "entries": [make_entry(api)]})
    cases["registry_idempotent"] = df.validate_registry(valid) == valid

    def reg(*entries):
        return {"schema": "urn:zeus:procedure-registry:1", "version": 1, "entries": list(entries)}

    for name, change in (("schema_2", {"schema": "urn:zeus:procedure-registry:2"}), ("version_2", {"version": 2}), ("version_true", {"version": True}),
                         ("entries_empty", {"entries": []}), ("entries_duplicate", {"entries": [make_entry(api), make_entry(api)]}),
                         ("extra_field", {"extra": CANARY})):
        cases["registry_" + name] = attempt(lambda c=change: df.validate_registry({**reg(make_entry(api)), **c}))
    for name, change in (("id_empty", {"id": ""}), ("id_escape", {"id": "../escape"}), ("kind_operation", {"source_kind": "operation"}),
                         ("repository_empty", {"repository": ""}), ("paths_empty", {"allowed_paths": []}),
                         ("paths_escape", {"allowed_paths": ["../secrets"]}), ("paths_duplicate", {"allowed_paths": PATHS + PATHS}),
                         ("criteria_sha_bad", {"acceptance_criteria_sha256": "nope"}), ("remediation_auto_publish", {"remediation": "auto_publish"}),
                         ("unknown_field", {"unknown": CANARY})):
        cases["entry_" + name] = attempt(lambda c=change: df.validate_registry(reg(make_entry(api, **c))))
    cases["entry_missing_remediation"] = attempt(lambda: df.validate_registry(reg({k: v for k, v in make_entry(api).items() if k != "remediation"})))

    contract = df.work_contract(REPOSITORY, "council", {"allowed_paths": list(PATHS), "acceptance_criteria": list(CRITERIA)})
    cases["contract"] = contract
    cases["match_exact"] = df.match_registry(contract, df.validate_registry(reg(make_entry(api))))
    cases["group_id_order_independent"] = df.group_id(contract) == df.group_id(df.work_contract(
        REPOSITORY, "council", {"allowed_paths": list(reversed(PATHS)), "acceptance_criteria": list(CRITERIA)}))
    for name, change in (("other_repository", {"repository": "other"}), ("other_paths", {"allowed_paths": ["docs/OTHER.md"]}),
                         ("other_criteria", {"acceptance_criteria_sha256": df.criteria_digest(["other criterion"])})):
        cases["match_" + name] = df.match_registry(contract, df.validate_registry(reg(make_entry(api, **change))))
    cases["match_ambiguous"] = df.match_registry(contract, df.validate_registry(reg(make_entry(api), make_entry(api, id="duplicate-contract"))))
    cases["criteria_digest_differs"] = [df.criteria_digest(CRITERIA) != df.criteria_digest(CRITERIA + ["second"]),
                                        df.criteria_digest(["a", "b"]) != df.criteria_digest(["b", "a"])]
    for name, broken in (("paths_empty", {"allowed_paths": [], "acceptance_criteria": CRITERIA}),
                         ("criteria_empty", {"allowed_paths": PATHS, "acceptance_criteria": []}),
                         ("criterion_blank", {"allowed_paths": PATHS, "acceptance_criteria": [""]})):
        cases["contract_" + name] = attempt(lambda b=broken: df.work_contract(REPOSITORY, "council", b))
    states = {status: df.outcome_facts({"id": "r", "status": status, "reason_code": "promoted"})
              for status in ("running", "accepted", "rejected", "failed", "cancelled", "exhausted", "needs_user", "needs_research", "expired", "unknown")}
    cases["outcomes"] = states
    cases["outcome_no_status"] = df.outcome_facts({"id": "r"})
    cases["quality"] = df.quality_facts()
    members = []
    for index in range(df.MAX_OCCURRENCES + 5):
        members = df.add_member(members, "run-%04d" % index)["run_ids"]
    window = df.occurrence_window(members)
    full = ["run-%05d" % index for index in range(df.MAX_MEMBERS)]
    cases["membership"] = {"members": len(members), "distinct": len(set(members)), "known_adds_nothing": df.add_member(members, members[0]) == {"run_ids": members, "capped": False},
                           "window": [len(window["referenced"]), window["unreferenced"]],
                           "window_does_not_grow": df.occurrence_window(window["referenced"])["unreferenced"],
                           "capped": df.add_member(full, "run-beyond") == {"run_ids": full, "capped": True},
                           "known_never_trips_cap": df.add_member(full, full[0]) == {"run_ids": full, "capped": False},
                           "limit_names_bound": [limit for limit in df.LIMITS if "membership is exact" in limit]}
    return {"pure": cases}


def c_collect(api):
    cases = {}

    # two distinct runs -> one candidate; repeated collection idempotent (test_two_distinct_council_runs_...)
    w = world(api)
    w.seed_run("council-001")
    cases["one_run_no_candidate"] = {"m7_test": "test_two_distinct_council_runs_make_one_candidate_and_repeated_collection_is_idempotent",
                                     **w.call(w.collect), "candidates": w.rows(api.CANDIDATES), "observations": w.rows(api.OBSERVATIONS),
                                     "groups": w.rows(api.GROUPS)}
    w.seed_run("council-002")
    snapshot = w.snapshot()
    second = w.call(w.collect)
    cases["two_runs_make_one_candidate"] = {"m7_test": "test_two_distinct_council_runs_make_one_candidate_and_repeated_collection_is_idempotent", **second,
                                            "candidates": w.rows(api.CANDIDATES), "groups": w.rows(api.GROUPS),
                                            "observations": w.rows(api.OBSERVATIONS), "collections": len(w.rows(api.COLLECTIONS)),
                                            "source_rows_unchanged": w.snapshot() == snapshot,
                                            "incidents": w.rows("incidents"), "hooks": w.rows("hooks"), "knowledge_nodes": w.rows("knowledge_nodes"),
                                            "canary_in_candidates": CANARY in str(w.rows(api.CANDIDATES))}
    third = w.call(w.collect)
    cases["third_collection_changes_nothing"] = {"m7_test": "test_two_distinct_council_runs_make_one_candidate_and_repeated_collection_is_idempotent",
                                                 **third, "same_receipt_id": third["value"]["id"] == second["value"]["id"],
                                                 "candidates_equal": w.rows(api.CANDIDATES) == cases["two_runs_make_one_candidate"]["candidates"],
                                                 "canary_in_receipt": CANARY in str(third["value"]), "collections": len(w.rows(api.COLLECTIONS))}
    receipt = third["value"]

    # status and report (test_status_and_report_...)
    status = w.call(api.DecisionFeedback(w.store, w.clock).status)
    bounded = w.call(api.DecisionFeedback(w.store, w.clock).status, limit=1)
    cases["status"] = {"m7_test": "test_status_and_report_expose_counts_limits_and_no_promotion_authority", **status}
    cases["status_limit_1"] = {"m7_test": "test_status_and_report_expose_counts_limits_and_no_promotion_authority", **bounded}
    reader = api.DecisionFeedback(w.store, w.clock)
    cases["report_with_collection"] = {"m7_test": "test_status_and_report_expose_counts_limits_and_no_promotion_authority",
                                       **w.call(reader.report, collection_id=receipt["id"])}
    cases["report_missing_collection"] = {"m7_test": "test_status_and_report_expose_counts_limits_and_no_promotion_authority",
                                          **w.call(reader.report, collection_id="collection:missing")}
    cases["report_limit_1_after"] = {"m7_test": "none", **w.call(reader.report, limit=1)}
    cases["report_cursor_not_text"] = {"m7_test": "none", **w.call(reader.report, after=5)}
    for limit in (0, api.df.MAX_SCAN + 1, True, "10", None):
        cases["status_invalid_limit_%r" % (limit,)] = {"m7_test": "none", **w.call(reader.status, limit=limit)}

    # the window narrowed to two (test_a_group_past_the_reported_window_...)
    saved = api.df.MAX_OCCURRENCES
    api.df.MAX_OCCURRENCES = 2
    try:
        w = world(api)
        for index in range(3):
            w.seed_run("council-%03d" % index)
        first = w.call(w.collect, limit=api.df.MAX_SCAN)
        candidate = w.rows(api.CANDIDATES)
        group = w.rows(api.GROUPS)
        again = w.call(w.collect, limit=api.df.MAX_SCAN)
        cases["group_past_the_window"] = {"m7_test": "test_a_group_past_the_reported_window_keeps_exact_distinct_membership_across_collections",
                                          "window": api.df.MAX_OCCURRENCES, "first": first, "candidates": candidate, "groups": group, "second": again,
                                          "candidates_unchanged": w.rows(api.CANDIDATES) == candidate,
                                          "groups_unchanged_but_updated_at": [{k: v for k, v in g.items() if k != "updated_at"} for g in w.rows(api.GROUPS)]
                                          == [{k: v for k, v in g.items() if k != "updated_at"} for g in group],
                                          "observations": len(w.rows(api.OBSERVATIONS))}
    finally:
        api.df.MAX_OCCURRENCES = saved

    # a different contract, a v1 source, another repository (test_one_run_a_different_contract_...)
    w = world(api)
    w.seed_run("council-001")
    w.seed_run("council-002", plan=dict(OTHER_PLAN))
    receipt = w.call(w.collect)
    cases["different_contract_stays_separate"] = {"m7_test": "test_one_run_a_different_contract_or_a_v1_source_never_groups_into_a_candidate",
                                                  **receipt, "candidates": w.rows(api.CANDIDATES), "groups": len(w.rows(api.GROUPS)),
                                                  "observations": len(w.rows(api.OBSERVATIONS))}
    w.seed_run("auto-001", council=False)
    cases["v1_source_earns_no_credit"] = {"m7_test": "test_one_run_a_different_contract_or_a_v1_source_never_groups_into_a_candidate", **w.call(w.collect),
                                          "observations": len(w.rows(api.OBSERVATIONS))}
    cases["foreign_repository"] = {"m7_test": "test_one_run_a_different_contract_or_a_v1_source_never_groups_into_a_candidate",
                                   **w.call(w.collect, registry=w.registry(make_entry(api, repository="elsewhere")), repository="elsewhere"),
                                   "candidates": w.rows(api.CANDIDATES)}

    # pending -> terminal -> a changed terminal history (test_a_pending_outcome_joins_later_...)
    w = world(api)
    w.seed_run("council-001")
    w.seed_run("council-002")
    terminal = w.edit(api.RUNS, "council-001", status="running", reason_code=None, finished_at=None)
    pending = w.call(w.collect)
    observation = [o for o in w.rows(api.OBSERVATIONS) if o["run_id"] == "council-001"][0]
    cases["pending_outcome"] = {"m7_test": "test_a_pending_outcome_joins_later_and_a_changed_terminal_history_is_a_conflict", **pending,
                                "observation": observation, "candidates": w.rows(api.CANDIDATES)}
    put(w.store, api.RUNS, "council-001", terminal)
    joined = w.call(w.collect)
    updated = [o for o in w.rows(api.OBSERVATIONS) if o["run_id"] == "council-001"][0]
    cases["pending_joins_terminal"] = {"m7_test": "test_a_pending_outcome_joins_later_and_a_changed_terminal_history_is_a_conflict", **joined,
                                       "observation": updated, "first_seen_unchanged": updated["first_seen_at"] == observation["first_seen_at"],
                                       "candidates": w.rows(api.CANDIDATES), "conflicts": w.rows(api.CONFLICTS)}
    w.edit(api.RUNS, "council-001", status="failed", reason_code="review_rejected")
    conflicted = w.call(w.collect)
    cases["terminal_history_conflict"] = {"m7_test": "test_a_pending_outcome_joins_later_and_a_changed_terminal_history_is_a_conflict", **conflicted,
                                          "observation": [o for o in w.rows(api.OBSERVATIONS) if o["run_id"] == "council-001"][0],
                                          "conflicts": w.rows(api.CONFLICTS), "candidates": w.rows(api.CANDIDATES)}
    again = w.call(w.collect)
    cases["conflict_not_duplicated"] = {"m7_test": "test_a_pending_outcome_joins_later_and_a_changed_terminal_history_is_a_conflict", **again,
                                        "conflicts": len(w.rows(api.CONFLICTS))}
    # the decision itself changes after it was observed (decision_changed): none of M7's tests names it
    w.edit(api.SESSIONS, "dge-council-002", base_revision="b" * 40)
    changed = w.call(w.collect)
    cases["decision_changed_conflict"] = {"m7_test": "none", **changed, "conflicts": w.rows(api.CONFLICTS)}

    # a stale page (test_a_page_read_before_the_terminal_outcome_is_stale_...)
    w = world(api)
    w.seed_run("council-001")
    w.seed_run("council-002")
    terminal = w.edit(api.RUNS, "council-001", status="running", reason_code=None, finished_at=None)
    fast = {}

    def between():
        put(w.store, api.RUNS, "council-001", terminal)
        fast.update(w.collect())

    late_feedback = api.DecisionFeedback(Interleaved(w.store, between), w.clock, evidence=w.evidence)
    late = w.call(w.collect, feedback=late_feedback)
    stored = [o for o in w.rows(api.OBSERVATIONS) if o["run_id"] == "council-001"][0]
    cases["stale_page"] = {"m7_test": "test_a_page_read_before_the_terminal_outcome_is_stale_and_not_a_changed_history", "fast": brief(fast), **late,
                           "stored": stored, "conflicts": w.rows(api.CONFLICTS), "reason_code_known": "source_page_stale" in api.df.RECORD_REASONS,
                           "candidates": w.rows(api.CANDIDATES)}
    w.edit(api.RUNS, "council-001", status="failed", reason_code="review_rejected")
    control = w.call(w.collect)
    cases["stale_control_real_change_conflicts"] = {"m7_test": "test_a_page_read_before_the_terminal_outcome_is_stale_and_not_a_changed_history", **control,
                                                    "conflicts": w.rows(api.CONFLICTS),
                                                    "stored_unchanged": [o for o in w.rows(api.OBSERVATIONS) if o["run_id"] == "council-001"][0] == stored}

    # a source row that cannot be re-read (test_a_source_row_that_cannot_be_re_read_...)
    w = world(api)
    w.seed_run("council-001")
    w.seed_run("council-002")
    terminal = w.edit(api.RUNS, "council-001", status="running", reason_code=None, finished_at=None)
    w.collect()
    put(w.store, api.RUNS, "council-001", terminal)
    before = w.rows(api.OBSERVATIONS)

    def row_unavailable():
        row = get(w.store, api.RUNS, "council-001")
        put(w.store, api.RUNS, "council-001", {**row, "id": "another-run"})

    feedback = api.DecisionFeedback(Interleaved(w.store, row_unavailable), w.clock, evidence=w.evidence)
    unavailable = w.call(w.collect, feedback=feedback)
    cases["source_row_unavailable"] = {"m7_test": "test_a_source_row_that_cannot_be_re_read_stays_unknown_and_writes_nothing",
                                       "reason_code_known": "source_row_unavailable" in api.df.RECORD_REASONS, **unavailable,
                                       "observations_unchanged": w.rows(api.OBSERVATIONS) == before, "conflicts": w.rows(api.CONFLICTS)}
    return {"collect": cases}


def d_evidence(api):
    cases = {}

    def breaker(name, m7, setup, runs=1):
        w = world(api)
        for index in range(runs):
            w.seed_run("council-%03d" % (index + 1))
        setup(w)
        out = w.call(w.collect)
        cases[name] = {"m7_test": m7, **out, "observations": w.rows(api.OBSERVATIONS), "groups": w.rows(api.GROUPS), "candidates": w.rows(api.CANDIDATES),
                       "conflicts": w.rows(api.CONFLICTS), "canary_echoed": CANARY in str(out["value"] if "value" in out else out)}

    m7 = "test_an_unproven_decision_identity_refuses_evidence_credit"
    rows_of = lambda w: w.runs["council-001"]  # noqa: E731
    breaker("task_execution_ref_changed", m7, lambda w: w.edit(api.TASKS, rows_of(w)["task"], result={
        **get(w.store, api.TASKS, rows_of(w)["task"])["result"], "execution_ref": "sha256:" + "9" * 64}))
    breaker("task_status_failed", m7, lambda w: w.edit(api.TASKS, rows_of(w)["task"], status="failed"))
    breaker("event_origin_operator", m7, lambda w: w.edit(api.EVENTS, rows_of(w)["event"], origin="operator_submitted"))
    breaker("session_owner_other", m7, lambda w: w.edit(api.SESSIONS, rows_of(w)["session"], owner="someone-else"))
    breaker("session_origin_operator", m7, lambda w: w.edit(api.SESSIONS, rows_of(w)["session"], origin="operator_submitted"))
    breaker("run_identity_empty", m7, lambda w: w.edit(api.RUNS, "council-001", identity={}))
    # branches no M7 test names
    breaker("run_identity_not_a_dict", "none", lambda w: w.edit(api.RUNS, "council-001", identity="r"))
    breaker("run_without_session", "none", lambda w: w.edit(api.RUNS, "council-001", session_id=None))
    breaker("session_absent", "none", lambda w: put(w.store, api.SESSIONS, rows_of(w)["session"], None) if False else
            w.edit(api.RUNS, "council-001", session_id="dge-missing"))
    breaker("session_history_empty", "none", lambda w: w.edit(api.SESSIONS, rows_of(w)["session"], history=[]))
    breaker("event_binding_missing", "none", lambda w: w.edit(api.EVENTS, rows_of(w)["event"], binding=None))
    breaker("event_wrong_agent", "none", lambda w: w.edit(api.EVENTS, rows_of(w)["event"], binding={
        **get(w.store, api.EVENTS, rows_of(w)["event"])["binding"], "agent": "lead:dba"}))
    breaker("event_packet_digest_changed", "none", lambda w: w.edit(api.EVENTS, rows_of(w)["event"], event={
        **get(w.store, api.EVENTS, rows_of(w)["event"])["event"], "packet_digest": "6" * 64}))
    breaker("run_role_binding_missing", "none", lambda w: w.edit(api.RUNS, "council-001", roles={}))
    breaker("run_output_sha_changed", "none", lambda w: w.edit(api.RUNS, "council-001", roles={api.df.DECIDING_ROLE: {
        **get(w.store, api.RUNS, "council-001")["roles"][api.df.DECIDING_ROLE], "output_sha256": "7" * 64}}))
    breaker("task_attempt_changed", "none", lambda w: w.edit(api.TASKS, rows_of(w)["task"], attempt=2))
    breaker("plan_without_paths", "none", lambda w: w.edit(api.SESSIONS, rows_of(w)["session"], plan={"allowed_paths": [], "acceptance_criteria": CRITERIA}))
    breaker("plan_not_a_dict", "none", lambda w: w.edit(api.SESSIONS, rows_of(w)["session"], plan="plan"))
    breaker("plan_criteria_blank", "none", lambda w: w.edit(api.SESSIONS, rows_of(w)["session"], plan={"allowed_paths": PATHS, "acceptance_criteria": [""]}))

    # the stored artifact (test_only_the_stored_execution_artifact_earns_evidence_credit_...)
    m7 = "test_only_the_stored_execution_artifact_earns_evidence_credit_never_a_matching_reference"
    breaker("artifacts_detached", m7, lambda w: w.evidence.documents.clear(), runs=2)

    def corrupt(w):
        for info in w.runs.values():
            w.evidence.faults[info["ref"]] = "evidence_corrupt"

    breaker("artifacts_corrupt", m7, corrupt, runs=2)

    def invalid(w):
        for info in w.runs.values():
            w.evidence.faults[info["ref"]] = "evidence_invalid"

    breaker("artifacts_invalid", "none", invalid, runs=2)

    def generic(w):
        for info in w.runs.values():
            w.evidence.faults[info["ref"]] = "generic"

    breaker("artifacts_port_without_fixed_codes", "none", generic, runs=2)

    def unknown_code(w):
        for info in w.runs.values():
            w.evidence.faults[info["ref"]] = "something_else"

    breaker("artifacts_unknown_reason_code", "none", unknown_code, runs=2)

    def swap(w):
        refs = [w.runs[r]["ref"] for r in sorted(w.runs)]
        for run_id, other in zip(sorted(w.runs), reversed(refs)):
            info = w.runs[run_id]
            event = get(w.store, api.EVENTS, info["event"])
            w.edit(api.EVENTS, info["event"], binding={**event["binding"], "execution_ref": other})
            task = get(w.store, api.TASKS, info["task"])
            w.edit(api.TASKS, info["task"], result={**task["result"], "execution_ref": other})
            run = get(w.store, api.RUNS, run_id)
            binding = run["roles"][api.df.DECIDING_ROLE]
            w.edit(api.RUNS, run_id, roles={**run["roles"], api.df.DECIDING_ROLE: {**binding, "execution_ref": other}})

    breaker("artifacts_swapped", m7, swap, runs=2)

    def swap_documents(w):
        refs = [w.runs[r]["ref"] for r in sorted(w.runs)]
        first, second = w.evidence.documents[refs[0]], w.evidence.documents[refs[1]]
        w.evidence.documents[refs[0]], w.evidence.documents[refs[1]] = second, first

    breaker("artifact_bodies_exchanged", "none", swap_documents, runs=2)

    def answer_mismatch(w):
        info = w.runs["council-001"]
        task = get(w.store, api.TASKS, info["task"])
        w.edit(api.TASKS, info["task"], result={**task["result"], "rationale": "changed after the fact"})

    breaker("task_answer_differs_from_artifact", "none", answer_mismatch)
    breaker("reservation_unsettled", "none", lambda w: w.edit(api.RESERVATIONS, w.runs["council-001"]["reservation"], status="open"))
    breaker("reservation_outcome_not_accepted", "none", lambda w: w.edit(api.RESERVATIONS, w.runs["council-001"]["reservation"], outcome="rejected"))
    breaker("reservation_other_stage", "none", lambda w: w.edit(api.RESERVATIONS, w.runs["council-001"]["reservation"], stage="dge:other"))
    breaker("reservation_absent", "none", lambda w: w.edit(api.RESERVATIONS, w.runs["council-001"]["reservation"], id="another-reservation"))
    breaker("artifact_basis_revision_other", "none", lambda w: w.edit(api.SESSIONS, w.runs["council-001"]["session"], base_revision="c" * 40))

    # the control
    w = world(api)
    w.seed_run("council-001")
    w.seed_run("council-002")
    verified = w.call(w.collect)
    cases["real_artifacts_verify"] = {"m7_test": "test_the_real_artifacts_of_the_same_two_runs_do_verify", **verified,
                                      "evidence": [o["evidence"] for o in w.rows(api.OBSERVATIONS)], "reads": len(w.evidence.reads),
                                      "output_sha_distinct": len({o["evidence"]["artifact"]["output_sha256"] for o in w.rows(api.OBSERVATIONS)})}
    cases["no_evidence_port"] = {"m7_test": "test_the_real_artifacts_of_the_same_two_runs_do_verify",
                                 **w.call(w.collect, feedback=api.DecisionFeedback(w.store, w.clock))}
    return {"evidence": cases}


def e_scan(api):
    cases = {}
    w = world(api)
    w.seed_run("council-001")
    w.seed_run("council-002")
    m7 = "test_a_bounded_scan_reports_truncation_and_continues_from_the_cursor"
    first = w.call(w.collect, limit=1)
    cases["limit_1_truncated"] = {"m7_test": m7, **first, "candidates": w.rows(api.CANDIDATES)}
    cursor = first["value"]["next_cursor"]
    second = w.call(w.collect, limit=1, after=cursor)
    cases["continues_from_cursor"] = {"m7_test": m7, **second, "candidates": w.rows(api.CANDIDATES),
                                      "limit_names_cursor": [x for x in api.df.LIMITS if "continuation cursor" in x]}
    for limit in (0, api.df.MAX_SCAN + 1, True, "10", None):
        cases["invalid_limit_%r" % (limit,)] = {"m7_test": m7, **w.call(w.collect, limit=limit)}
    for name, revision, path, sha_value in (("revision_short", REVISION[:39], "docs/p.json", REGISTRY_SHA), ("revision_head", "HEAD", "docs/p.json", REGISTRY_SHA),
                                            ("path_escape", REVISION, "../p.json", REGISTRY_SHA), ("sha_invalid", REVISION, "docs/p.json", "not-a-digest")):
        cases["pin_" + name] = {"m7_test": m7, **w.call(w.collect, registry_revision=revision, registry_path=path, registry_sha256=sha_value)}
    cases["repository_blank"] = {"m7_test": "none", **w.call(w.collect, repository="  ")}
    cases["repository_not_text"] = {"m7_test": "none", **w.call(w.collect, repository=None)}
    cases["after_not_text"] = {"m7_test": "none", **w.call(w.collect, after=5)}
    cases["registry_invalid"] = {"m7_test": "none", **w.call(w.collect, registry={"schema": "urn:zeus:procedure-registry:2", "version": 1, "entries": []})}
    cases["registry_not_a_dict"] = {"m7_test": "none", **w.call(w.collect, registry=[])}
    cases["after_the_last_run_scans_nothing"] = {"m7_test": "none", **w.call(w.collect, after="council-002")}

    # a store failure is unavailable, not zero samples (test_a_store_failure_is_unavailable_not_zero_samples)
    for name, store in (("broken_store", BrokenStore()), ("broken_scan", BrokenScan())):
        feedback = api.DecisionFeedback(store, w.clock, evidence=Evidence(api))
        cases[name] = {"m7_test": "test_a_store_failure_is_unavailable_not_zero_samples",
                       "collect": observe(lambda f=feedback: w.collect(feedback=f)), "status": observe(feedback.status), "report": observe(feedback.report)}

    # concurrent collectors serialize (test_concurrent_collectors_serialize_...): the final state only, the receipts race
    w = world(api)
    w.seed_run("council-001")
    w.seed_run("council-002")
    errors = []

    def worker():
        try:
            w.collect()
        except Exception as exc:  # noqa: BLE001
            errors.append(type(exc).__name__)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    candidates, groups = w.rows(api.CANDIDATES), w.rows(api.GROUPS)
    cases["concurrent_collectors"] = {"m7_test": "test_concurrent_collectors_serialize_into_one_candidate_and_one_set_of_occurrences", "errors": errors,
                                      "candidates": len(candidates), "distinct_runs": candidates[0]["distinct_runs"], "groups": len(groups),
                                      "occurrences": [o["run_id"] for o in candidates[0]["occurrences"]],
                                      "observations": len(w.rows(api.OBSERVATIONS)), "collections": len(w.rows(api.COLLECTIONS))}
    return {"scan": cases}


def observe(fn):
    try:
        return {"outcome": "returned", "value": fn()}
    except BaseException as exc:  # noqa: BLE001
        return {"outcome": "raised", "type": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc),
                "cause_type": None if exc.__cause__ is None else type(exc.__cause__).__name__}


def run(api) -> dict:
    groups = {}
    for step in (a_surface, b_pure, c_collect, d_evidence, e_scan):
        groups.update(step(api))
    counts = {k: len(v) for k, v in groups.items()}
    return {**groups, "m7_tests": M7_TESTS, "cases_per_group": counts}

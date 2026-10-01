"""Shared S8 scenario steps (`research.audit_progress`): M7 `application/audit_progress.py` (`packaged_policy`, `_seconds`,
`AuditProgress`: `_facts`, `_evidence`, `observe`, `_observe`, `_apply`, `_start_epoch`, `_close_window`, `_candidate`, `_record`,
`_degraded`, `state`, `windows`, `candidates`; `status_view`), characterized BEFORE the module moves (DESIGN-s8 §2 row
`research.audits`, sub-family `research.audit_progress`, and §6 V11 step 5). The golden is placement-neutral: it observes SOURCE
behaviour only; the move is the NEXT pilot.

- **g1_policy**: the packaged policy validated, a broken one refused and never defaulted, the opt-in and bounded source (M7
  `test_the_packaged_policy_is_validated_and_a_broken_one_is_refused_not_defaulted`, `test_the_audit_progress_source_is_opt_in_...`).
- **g2_windows**: the baseline, one window closing per reading, overflow cohorts (nondivisible and divisible), duplicate ticks,
  live work and restart, which task rows are settled.
- **g3_yield**: low-yield streaks, semantic gain, generated/duplicate/binary completions, subsystem-only gain, regressions, a
  completed audit, the verdict order.
- **g4_evidence**: unreadable evidence is unknown and never zero; malformed evidence; distinct ranges; state changing during
  verification writes nothing.
- **g5_epochs**: a changed scope, policy, release or revision starts a new epoch.
- **g6_candidates**: two low windows produce one research-required candidate; an owner disposition survives; the eligibility
  rule over the rows this module wrote.
- **g7_degraded_status**: an unknown or unpartitioned audit, a malformed stored record and a store fault are degraded and never a
  known zero; `status_view`; the read-only `state`, `windows` and `candidates`.
- **g8_owner_rows**: the observer over rows `ResearchAudits` and `Workflow` themselves wrote (M7's own owners, as SOURCE runs them).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a
target) driver builds. LABELLED doubles (nothing here is an actual Codex, Git, Docker or production verification):
- the artifacts are M7's OWN `adapters.artifacts.FileArtifacts` over a run-scoped directory (its target counterpart is
  `storage.adapters.file_artifacts.FileArtifacts`);
- the audit rows (`research_audits`, `research_partitions`, `research_paths`, `research_subsystems`, `research_observed_assets`,
  `research_receipts`) and the settled `tasks` rows of g1-g7 are PLANTED, LABELLED synthetic records in the shape their owners
  write (M7 `tests/test_audit_progress.py` `World`); g8 and the cases it names run the owners instead;
- the clock is the harness's ticking fake clock: every reading advances it one minute, so elapsed seconds are observed.
Where a state has no honest call path (a planted malformed row, a store fault, an artifact store that fails or races) the case is
LABELLED where it is made. The store digests of the three buckets `AuditProgress` writes are recorded before and after every
observation and every refusal, with a flag that no other bucket changed.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace

import s8_audit_core as AC
import s8_research_program as R

AUDIT = "audit-fixture-001"
REV = "r" * 40
PATHS = ["cGF0aC0w", "cGF0aC0x", "cGF0aC0y", "cGF0aC0z"]   # base64 inventory paths, as Git audits store them
SUBSYSTEMS = ["core"]
STEP_SECONDS = 60
CANARY = R.CANARY


class StoreFault(RuntimeError):
    """LABELLED. An injected store failure: no real outage happened."""


def short(value):
    return None if value is None else str(value)[:12]


# ---- the world --------------------------------------------------------------------------------------------------------------
class World:
    """M7 `World`: one LABELLED audit in a real `MemoryStore` with M7's own `FileArtifacts`; the rows are planted in the shape
    their owners write. `settle` plants terminal `tasks` rows; no execution ran."""

    def __init__(self, api, ws, name, audit_id=AUDIT, store=None, partitions=True):
        self.api, self.ws, self.name = api, ws, name
        self.store = store or api.MemoryStore()
        self.artifacts = api.FileArtifacts(str(ws.case(name) / "artifacts"))
        self.audit_id, self.executions, self.reads = audit_id, 0, 0
        self.source = api.SourceIdentity("https://github.com/fixture/repo", "a" * 40, "b" * 40, "sha256:" + "0" * 64)
        self.put("research_audits", audit_id, {
            "id": audit_id, "version": 1, "source": asdict(self.source),
            "inventory": [{"path": p, "mode": "100644", "object_id": "%040d" % n, "size": 10, "artifact_ref": "sha256:" + "%064d" % n}
                          for n, p in enumerate(PATHS)],
            "subsystems": list(SUBSYSTEMS), "status": "source_verified_not_reviewed"})
        if partitions:
            self.partition("p-1", PATHS[:2])
            self.partition("p-2", PATHS[2:])

    # -- planting
    def put(self, bucket, key, body):
        with self.store.transaction() as tx:
            tx.put(bucket, key, body)

    def partition(self, partition_id, paths, remaining=None, open_questions=()):
        checkpoint = self.api.PartitionCheckpoint(self.audit_id, partition_id, 0, list(paths), [], [],
                                                  list(paths if remaining is None else remaining), [], list(open_questions), "pending")
        checkpoint.validate()
        self.put("research_partitions", partition_id, asdict(checkpoint))

    def task(self, key, status="succeeded", audit_id=None, **extra):
        body = {"id": key, "status": status, "generation": 1, "attempt": 1,
                "message": {"what": {"action": "audit_partition",
                                     "details": {"audit_id": audit_id or self.audit_id, "partition_id": "p-1"}}}}
        body.update(extra)
        self.put("tasks", key, body)

    def settle(self, count=1, status="succeeded"):
        for _ in range(count):
            self.executions += 1
            key = "task-%03d" % self.executions
            self.task(key, status, completed_at="2028-01-01T00:%02d:00+00:00" % (self.executions % 60))
        return self.executions

    def live(self, count=1, status="running"):
        for index in range(count):
            key = "live-%03d" % index
            self.put("tasks", key, {"id": key, "status": status, "generation": 1, "attempt": 1,
                                    "message": {"what": {"details": {"audit_id": self.audit_id}}}})

    def cover(self, path, disposition="semantic", audit_id=None, item=None):
        """A coverage row in the shape `ResearchAudits.checkpoint` writes, with the REAL `PathDisposition` record."""
        reviewed = disposition not in ("unreviewed", "unavailable")
        record = self.api.PathDisposition(path, disposition, ["sha256:" + "1" * 64] if reviewed else [], [],
                                          "fixture justification" if reviewed else "",
                                          [p for p in PATHS if p != path][:1] if disposition in ("generated", "duplicate") else [],
                                          "read", ["receipt-1"] if disposition == "binary" else [])
        record.validate()
        audit_id = audit_id or self.audit_id
        self.put("research_paths", self.api.digest({"audit": audit_id, "item": item or path}),
                 {"audit_id": audit_id, "record": asdict(record), "task_id": "task-001", "generation": 1})
        if audit_id == self.audit_id:
            self._remaining()

    def cover_subsystem(self, name="core", **overrides):
        values = dict(name=name, paths=list(PATHS), contracts=["contract"], entry_points=["entry"], implementations=["impl"],
                      callers=["caller"], configuration=["config"], storage_authority=["store"], failure_paths=["failure"],
                      tests=['["pytest"]'], receipt_ids=["receipt-1"], evidence_refs=["sha256:" + "1" * 64], contradictions=[],
                      unresolved_dependencies=[], tests_not_run=[])
        values.update(overrides)
        record = self.api.SubsystemAnalysis(**values)
        record.validate()
        self.put("research_subsystems", self.api.digest({"audit": self.audit_id, "item": name}),
                 {"audit_id": self.audit_id, "record": asdict(record), "task_id": "task-001", "generation": 1})

    def uncover(self, path):
        """A regressed semantic set: the row disappears (a rebuild, a purge or a rollback)."""
        with self.store.transaction() as tx:
            tx.data.pop(("research_paths", self.api.digest({"audit": self.audit_id, "item": path})), None)
        self._remaining()

    def _remaining(self):
        with self.store.transaction() as tx:
            covered = {self.api.PathDisposition(**row["record"]).path for row in tx.scan("research_paths")
                       if row["audit_id"] == self.audit_id and row["record"]["disposition"] not in ("unreviewed", "unavailable")}
            for row in tx.scan("research_partitions"):
                if row["audit_id"] == self.audit_id:
                    tx.put("research_partitions", row["partition_id"], {**row, "remaining_paths": [p for p in row["paths"] if p not in covered]})

    def asset(self, path, state="unreviewed_observed_asset"):
        """A pending observed-asset row (INV-RESEARCH-001's separate ledger) in the shape `observe_assets` writes."""
        record = self.api.ObservedAsset(AC.b64(path.encode()), "observed", state, None, None, [])
        record.validate()
        self.put("research_observed_assets", self.api.digest({"audit": self.audit_id, "asset": path}),
                 {"audit_id": self.audit_id, "record": asdict(record)})

    def body(self, path=None, start=0, **overrides):
        path = path or PATHS[0]
        body = {"path": path, "lines": ["fixture line"], "start_line": start, "start_char": 0, "next_line": start + 1,
                "next_char": 0, "total_lines": 9, "partial_last_line": False, "eof": False, "object_id": "object-" + path,
                "bytes_sha256": "c" * 64}
        body.update(overrides)
        return body

    def read(self, path=None, start=0, text=None, **overrides):
        """A source-read receipt with the inert reader's output document (its shape) in the real artifact store."""
        self.reads += 1
        path = PATHS[0] if path is None else path
        text = text if text is not None else self.api.canonical(self.body(path, start, **overrides))
        ref = self.artifacts.put(text, "inert-source-inspection")["ref"]
        receipt = self.api.ExecutionReceipt(self.source, "env", ["source-read", path, str(start)], "inert-objects-no-code-execution",
                                            0, ref, "harness:fixture", False, passed=True, outcome="read")
        receipt.validate()
        self.put("research_receipts", "receipt-%03d" % self.reads,
                 {"audit_id": self.audit_id, "task_id": "task-001", "generation": 1, "receipt": asdict(receipt)})
        return ref

    def plant_receipt(self, name, receipt, audit_id=None):
        self.put("research_receipts", name, {"audit_id": audit_id or self.audit_id, "task_id": "task-001", "generation": 1, "receipt": receipt})

    def clock(self):
        """The harness fake clock, one minute per reading (M7 `Clock`)."""
        def tick():
            self.api.advance(STEP_SECONDS)
            return self.api.utcnow()
        return tick

    def observer(self, policy=None, clock=None, artifacts=None, store=None):
        return self.api.AuditProgress(store or self.store, artifacts or self.artifacts, policy=policy, clock=clock or self.clock())


# ---- observations -----------------------------------------------------------------------------------------------------------
def small(api, **overrides) -> dict:
    """The packaged policy with a smaller window, so a case closes windows without ten fixtures (M7 `small`)."""
    return {**api.packaged_policy(), "window_executions": 2, **overrides}


def written(api):
    return (api.BUCKET_STATE, api.BUCKET_WINDOWS, api.BUCKET_INVESTIGATIONS)


def snap(world) -> dict:
    """`bucket -> "<rows>:<digest16>"` of the three buckets `AuditProgress` writes, and `rest`, the digest of every other bucket
    (the authoritative audit rows, `tasks`, `research_*`, the schedule: this module never writes them)."""
    api = world.api
    with world.store.transaction() as tx:
        rows = tx.records()
    out = {}
    for bucket in written(api):
        mine = sorted([r["id"], R.canonical_digest(r["body"])] for r in rows if r["bucket"] == bucket)
        out[bucket] = "%d:%s" % (len(mine), R.canonical_digest(mine)[:16])
    out["rest"] = R.canonical_digest(sorted([r["bucket"], r["id"], R.canonical_digest(r["body"])]
                                            for r in rows if r["bucket"] not in written(api)))[:16]
    return out


def view(o) -> dict:
    """The facts of one observation; `digest` pins the whole document (its timestamps come from the fake clock)."""
    out = {"status": o["status"], "verdict": o["verdict"], "streak": o["streak"], "unknown": o["unknown"],
           "candidate": short(o["candidate"]), "candidate_created": o["candidate_created"], "epoch": short(o["epoch"]),
           "keys": sorted(o), "digest": R.canonical_digest(o)[:16]}
    if o["status"] == "degraded":
        out["reason_code"] = o["reason_code"]
        out["error_type"] = o.get("error_type")
        return out
    w = o["window"]
    out.update(window_index=o["window_index"], new_executions=o["new_executions"], evidence=o["evidence"],
               metrics={k: o["metrics"][k] for k in ("semantic_paths", "semantic_subsystems", "non_semantic", "remaining_paths",
                                                    "remaining_subsystems", "open_questions", "executions", "distinct_ranges",
                                                    "unknown", "complete")},
               window=None if w is None else {"index": w["index"], "verdict": w["verdict"], "comparable": w["comparable"],
                                              "verdict_reason": w["verdict_reason"], "executions": w["executions"], "delta": w["delta"]})
    return out


def observe(world, observer, audit_id=None, release="release-1", revision=REV, **kwargs):
    """One `observe` with the store digests before and after (a degraded or repeated observation changes none of them)."""
    before = snap(world)
    outcome = observer.observe(world.audit_id if audit_id is None else audit_id, release_id=release, revision=revision, **kwargs)
    after = snap(world)
    world.api.advance(0.001)
    return {**view(outcome), "before": before, "after": after, "changed": [k for k in before if before[k] != after[k]],
            "authority_unchanged": before["rest"] == after["rest"]}


def close(world, observer, executions=2, evidence=True, **kwargs):
    """Settle a window's worth of executions (optionally with new read evidence) and observe (M7 `close`)."""
    if evidence:
        world.read(start=world.reads)
    world.settle(executions)
    return observe(world, observer, **kwargs)


def call(world, fn, *args, **kwargs):
    """The outcome of one call: a digest and shape of its value, or the refusal (type, reason code and field; an OS error by type),
    with the store digests before and after."""
    before = snap(world)
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:   # the refusal is the characterized result
        out = {"raised": type(exc).__name__}
        for name in ("reason_code", "field"):
            if hasattr(exc, name):
                out[name] = getattr(exc, name)
        if not isinstance(exc, OSError):
            out["message"] = str(exc)[:200]
    else:
        out = {"value": R.canonical_digest(value)[:16]}
    return {**out, "before": before, "after": snap(world), "unchanged": before == snap(world)}


def scan(world, bucket):
    with world.store.transaction() as tx:
        return tx.scan(bucket)


def definitions() -> dict:
    """M7 `_definitions`: the portfolio definitions the owner's `Portfolio` is built over."""
    return {"schema": "urn:zeus:portfolio-definitions:1", "projects": [
        {"id": "ops", "title": "Operations", "outcome": "bound work completes", "source_ref": "docs/GOAL.md",
         "criteria": [{"id": "c1", "text": "jobs reach acceptance"}]}]}


def windows_view(world, observer):
    return [{"index": w["index"], "epoch": short(w["epoch"]), "verdict": w["verdict"], "comparable": w["comparable"],
             "reason": w["verdict_reason"], "executions": w["executions"], "members": w["members"],
             "members_sha256": short(w["members_sha256"]), "delta": w["delta"],
             "opened_at": w["opened_at"], "closed_at": w["closed_at"]}
            for w in observer.windows(world.audit_id)]


def candidate_view(row):
    return {"id": short(row["id"]), "kind": row["kind"], "state": row["state"], "audit_id": row["audit_id"], "epoch": short(row["epoch"]),
            "reason_code": row["reason_code"], "windows": [short(w) for w in row["windows"]], "count": row["count"],
            "keys": sorted(row), "observations": [{k: (short(v) if k == "window" else v) for k, v in o.items()} for o in row["observations"]],
            "evidence_refs": row["evidence_refs"], "decided_at": row["decided_at"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "metrics_complete": row["metrics"]["complete"],
            "policy_matches": row["policy_sha256"] == row["epoch_scope"]["policy_sha256"]}


def candidates_view(observer, audit_id=None):
    return [candidate_view(r) for r in observer.candidates(audit_id)]


def state_view(observer, audit_id=AUDIT):
    s = observer.state(audit_id)
    if s is None:
        return None
    return {"epoch": short(s["epoch"]["id"]), "epochs": s["epochs"], "streak": s["streak"], "windows_completed": s["windows_completed"],
            "window_index": s["window"]["index"], "opened_at": s["window"]["opened_at"], "counted": len(s["counted"]),
            "baseline_executions": s["baseline"]["executions"], "candidate": short(s["candidate"]), "last_verdict": s["last_verdict"],
            "created_at": s["created_at"], "updated_at": s["updated_at"], "keys": sorted(s)}


def constructed(world, policy="UNSET", **kwargs):
    """`AuditProgress(...)`: the validated policy and its digest, or the refusal (never a defaulted policy)."""
    api = world.api
    before = snap(world)
    try:
        observer = (api.AuditProgress(world.store, world.artifacts, **kwargs) if policy == "UNSET"
                    else api.AuditProgress(world.store, world.artifacts, policy=policy, **kwargs))
    except Exception as exc:   # the refusal is the characterized result
        out = {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "field": getattr(exc, "field", None),
               "message": str(exc)[:200]}
    else:
        out = {"constructed": True, "policy": observer.policy,
               "policy_sha256_matches": observer.policy_sha256 == api.policy_digest(observer.policy)}
    return {**out, "before": before, "after": snap(world), "unchanged": before == snap(world)}


# ---- g1 policy ---------------------------------------------------------------------------------------------------------------
def g1_policy(api, ws):
    out = {}
    world = World(api, ws, "policy")
    packaged = api.packaged_policy()
    validated = api.validate_policy(packaged)
    out["packaged_policy_resource"] = {"policy": packaged, "keys": sorted(packaged), "validated_equal": validated == packaged,
                                       "digest_stable": api.policy_digest(validated) == api.policy_digest(api.validate_policy(api.packaged_policy())),
                                       "window_executions": validated["window_executions"], "minimum_semantic_paths": validated["minimum_semantic_paths"],
                                       "low_yield_windows": validated["low_yield_windows"],
                                       "authority_says_never_model_input": "never model input" in validated["authority"]}
    out["packaged_policy_unknown_resource"] = call(world, api.packaged_policy, "no-such-policy.json")
    out["packaged_policy_is_a_fresh_document_each_call"] = {"equal": api.packaged_policy() == api.packaged_policy(),
                                                            "same_object": api.packaged_policy() is api.packaged_policy()}
    out["default_policy_is_the_validated_packaged_one"] = constructed(world)
    out["policy_none_is_the_default"] = constructed(world, None)
    out["a_valid_policy_is_kept_not_defaulted"] = constructed(world, small(api))
    # M7 `test_the_packaged_policy_is_validated_and_a_broken_one_is_refused_not_defaulted`, through the constructor
    for name, override in (("window_executions_zero", {"window_executions": 0}), ("window_executions_over_100", {"window_executions": 101}),
                           ("window_executions_bool", {"window_executions": True}), ("window_executions_string", {"window_executions": "2"}),
                           ("low_yield_windows_one", {"low_yield_windows": 1}), ("low_yield_windows_over_10", {"low_yield_windows": 11}),
                           ("minimum_semantic_paths_bool", {"minimum_semantic_paths": True}),
                           ("minimum_semantic_paths_zero", {"minimum_semantic_paths": 0}),
                           ("minimum_semantic_paths_over_1000", {"minimum_semantic_paths": 1001}),
                           ("version_two", {"version": 2}), ("extra_field", {"extra": 1}),
                           ("other_schema", {"schema": "urn:other:1"}), ("authority_empty", {"authority": ""}),
                           ("authority_blank", {"authority": "   "}), ("authority_not_a_string", {"authority": 7})):
        out["broken_" + name] = constructed(world, {**api.packaged_policy(), **override})
    out["version_true_is_accepted_because_true_equals_one"] = constructed(world, {**api.packaged_policy(), "version": True})
    missing = {k: v for k, v in api.packaged_policy().items() if k != "authority"}
    out["broken_missing_field"] = constructed(world, missing)
    out["broken_missing_schema"] = constructed(world, {k: v for k, v in api.packaged_policy().items() if k != "schema"})
    for name, document in (("empty_dict_is_not_defaulted", {}), ("a_list", []), ("a_string", "policy"), ("zero", 0), ("false", False)):
        out["broken_" + name] = constructed(world, document)
    # M7 `test_the_audit_progress_source_is_opt_in_bounded_and_keeps_the_legacy_config_identical` (the part that is the domain
    # function `validate_source`, called as the test calls it; the ResearchProgram config is another family)
    topics = {"storage", "other"}
    for name, document in (("valid", {"topic": "storage", "audit_ids": [AUDIT]}), ("null", None), ("not_a_dict", ["storage"]),
                           ("missing_topic", {"topic": "missing", "audit_ids": [AUDIT]}), ("topic_not_a_string", {"topic": 3, "audit_ids": [AUDIT]}),
                           ("empty_audit_ids", {"topic": "storage", "audit_ids": []}), ("wildcard", {"topic": "storage", "audit_ids": ["*"]}),
                           ("duplicate", {"topic": "storage", "audit_ids": [AUDIT, AUDIT]}),
                           ("extra_field", {"topic": "storage", "audit_ids": [AUDIT], "extra": 1}),
                           ("missing_field", {"topic": "storage"}), ("audit_ids_not_a_list", {"topic": "storage", "audit_ids": AUDIT}),
                           ("audit_id_not_a_string", {"topic": "storage", "audit_ids": [4]}),
                           ("ten_audits", {"topic": "storage", "audit_ids": ["a%d" % n for n in range(10)]}),
                           ("eleven_audits", {"topic": "storage", "audit_ids": ["a%d" % n for n in range(11)]}),
                           ("audit_id_128_chars", {"topic": "storage", "audit_ids": ["a" * 128]}),
                           ("audit_id_129_chars", {"topic": "storage", "audit_ids": ["a" * 129]})):
        out["source_" + name] = call(world, api.validate_source, document, topics)
    out["source_valid_is_returned_as_written"] = api.validate_source({"topic": "storage", "audit_ids": [AUDIT]}, topics)
    return out


# ---- g2 windows --------------------------------------------------------------------------------------------------------------
def g2_windows(api, ws):
    out = {}
    # M7 `test_the_baseline_excludes_history_and_exactly_one_window_closes_per_reading`
    world = World(api, ws, "baseline")
    world.settle(5)
    observer = world.observer(policy=small(api))
    out["baseline_excludes_history"] = baseline = {"first": observe(world, observer)}
    baseline["status_view_baseline_executions"] = api.status_view(observer.state(AUDIT))["baseline_executions"]
    world.settle(1)
    baseline["one_new_execution_is_not_a_window"] = observe(world, observer)
    baseline["no_window_yet"] = windows_view(world, observer)
    baseline["window_closes_with_its_own_executions"] = close(world, observer, executions=1)
    baseline["windows"] = windows_view(world, observer)
    baseline["state"] = state_view(observer)
    world = World(api, ws, "fresh")
    observer = world.observer(policy=small(api))
    out["baseline_at_the_audit_start_with_no_history"] = {"first": observe(world, observer), "state": state_view(observer)}
    # the packaged window of ten
    world = World(api, ws, "packaged")
    observer = world.observer()
    case = out["packaged_policy_window_of_ten"] = {"baseline": observe(world, observer)}
    world.settle(9)
    case["nine_executions_close_nothing"] = observe(world, observer)
    world.settle(1)
    case["the_tenth_closes_one_comparable_window"] = observe(world, observer)
    case["windows"] = windows_view(world, observer)
    # cohort shapes
    world = World(api, ws, "cohorts")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.settle(1)
    case = out["cohort_one_below_the_window"] = {"observed": observe(world, observer), "windows": len(observer.windows(AUDIT))}
    world.settle(1)
    case = out["cohort_exactly_the_window"] = {"observed": observe(world, observer), "windows": windows_view(world, observer)}
    # M7 `test_a_nondivisible_overflow_cohort_is_consumed_once_and_leaves_nothing_behind`
    world = World(api, ws, "overflow")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.settle(5)
    out["overflow_nondivisible"] = case = {"overflowed": observe(world, observer)}
    case["receipt_members"] = len(observer.windows(AUDIT)[0]["members"])
    case["repeat_reading_closes_nothing"] = observe(world, observer)
    case["restart_closes_nothing"] = observe(world, world.observer(policy=small(api)))
    case["windows_after_repeats"] = len(observer.windows(AUDIT))
    case["first_new_low_window_is_comparable"] = close(world, observer)
    case["second_new_low_window_creates_the_candidate"] = close(world, observer)
    case["window_sizes"] = [w["executions"] for w in observer.windows(AUDIT)]
    # M7 `test_gains_before_a_divisible_overflow_anchor_the_next_window_and_invent_no_strike`
    world = World(api, ws, "divisible")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.settle(4)
    world.cover(PATHS[0])
    world.cover(PATHS[1])
    out["overflow_divisible_anchors_the_next_window"] = case = {"overflowed": observe(world, observer)}
    case["receipt_windows"] = len(observer.windows(AUDIT))
    case["identical_reading"] = observe(world, observer)
    restarted = world.observer(policy=small(api))
    world.settle(2)
    case["restart_then_two_new_zero_gain_executions"] = observe(world, restarted)
    case["candidates_after"] = candidates_view(restarted, AUDIT)
    case["windows"] = len(restarted.windows(AUDIT))
    # overflow of exactly twice the window is still one cohort; overflow with one extra
    world = World(api, ws, "overflow-plus-one")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.settle(3)
    out["overflow_one_more_than_the_window"] = {"overflowed": observe(world, observer), "windows": windows_view(world, observer)}
    # M7 `test_duplicate_ticks_live_work_and_a_restart_do_not_create_extra_windows_or_strikes`
    world = World(api, ws, "duplicates")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.live(3)
    out["duplicate_ticks_live_work_and_restart"] = case = {"closed": close(world, observer)}
    case["duplicate_ticks"] = [observe(world, observer) for _ in range(3)]
    case["windows"] = len(observer.windows(AUDIT))
    case["state_streak"] = observer.state(AUDIT)["streak"]
    restarted = world.observer(policy=small(api))
    case["restart_resumes_the_same_epoch"] = resumed = close(world, restarted)
    case["same_epoch"] = resumed["epoch"] == case["closed"]["epoch"]
    case["windows_after_restart"] = len(restarted.windows(AUDIT))
    with world.store.transaction() as tx:
        case["live_rows_untouched"] = [row["status"] for row in tx.scan("tasks") if row["id"].startswith("live-")]
    # which task rows are settled
    for status in ("succeeded", "failed", "cancelled", "expired", "blocked", "superseded", "queued", "running", "retry", "pending", "bogus"):
        world = World(api, ws, "status-" + status)
        observer = world.observer(policy=small(api, window_executions=1))
        observe(world, observer)
        world.task("t-1", status)
        out["settled_status_" + status] = case = {"observed": observe(world, observer)}
        case["windows"] = [w["members"] for w in observer.windows(AUDIT)]
    world = World(api, ws, "task-shapes")
    observer = world.observer(policy=small(api, window_executions=3))
    observe(world, observer)
    world.task("t-a", completed_at="2028-01-01T00:05:00+00:00")
    world.task("t-other", audit_id="another-audit", completed_at="2028-01-01T00:01:00+00:00")
    world.put("tasks", "no-id", {"status": "succeeded", "message": {"what": {"details": {"audit_id": AUDIT}}}})
    world.put("tasks", "empty-id", {"id": "", "status": "succeeded", "message": {"what": {"details": {"audit_id": AUDIT}}}})
    world.put("tasks", "int-id", {"id": 7, "status": "succeeded", "message": {"what": {"details": {"audit_id": AUDIT}}}})
    world.put("tasks", "no-message", {"id": "t-nm", "status": "succeeded"})
    world.put("tasks", "no-details", {"id": "t-nd", "status": "succeeded", "message": {"what": {"action": "x"}}})
    world.put("tasks", "null-message", {"id": "t-null", "status": "succeeded", "message": None})
    world.task("t-created", created_at="2028-01-01T00:02:00+00:00")
    world.put("tasks", "t-bare", {"id": "t-bare", "status": "failed", "message": {"what": {"details": {"audit_id": AUDIT}}}})
    out["task_rows_that_count_and_that_do_not"] = case = {"observed": observe(world, observer)}
    case["members"] = [w["members"] for w in observer.windows(AUDIT)]
    case["state_counted"] = sorted(observer.state(AUDIT)["counted"])
    # an execution is its task, generation, attempt and status
    world = World(api, ws, "keys")
    observer = world.observer(policy=small(api, window_executions=1))
    observe(world, observer)
    world.task("t-key", generation=3, attempt=2)
    first = observe(world, observer)
    world.task("t-key", generation=4, attempt=1)
    second = observe(world, observer)
    out["an_execution_key_is_task_generation_attempt_and_status"] = {"first": first, "regenerated_task_is_a_new_execution": second,
                                                                     "members": [w["members"] for w in observer.windows(AUDIT)]}
    return out


# ---- g3 yield ----------------------------------------------------------------------------------------------------------------
def g3_yield(api, ws):
    out = {}
    # M7 `test_new_evidence_without_semantic_gain_is_low_yield_and_real_progress_clears_the_streak`
    world = World(api, ws, "lowyield")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    out["low_yield_then_adequate_then_no_evidence"] = case = {"low": close(world, observer)}
    world.cover(PATHS[0])
    case["real_progress_clears_the_streak"] = close(world, observer)
    case["no_candidate_yet"] = candidates_view(observer, AUDIT)
    world.cover(PATHS[1], disposition="unreviewed")
    case["a_disposition_only_change_with_no_evidence"] = close(world, observer, evidence=False)
    # M7 `test_generated_duplicate_and_binary_completions_are_valid_but_never_semantic_gain`
    world = World(api, ws, "nonsemantic")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.cover(PATHS[0], disposition="generated")
    world.cover(PATHS[1], disposition="duplicate")
    out["generated_duplicate_and_binary_are_never_semantic_gain"] = case = {"first": close(world, observer)}
    world.cover(PATHS[2], disposition="binary")
    case["binary_second"] = close(world, observer, evidence=False)
    case["candidates"] = candidates_view(observer, AUDIT)
    # M7 `test_one_semantic_path_clears_the_streak_and_a_subsystem_only_gain_does_not`
    world = World(api, ws, "subsystem")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.cover(PATHS[0])
    out["one_semantic_path_clears_and_a_subsystem_only_gain_does_not"] = case = {"semantic_path": close(world, observer)}
    world.cover_subsystem("core")
    case["subsystem_only"] = close(world, observer)
    # M7 `test_a_semantic_path_rewritten_as_a_valid_completion_is_a_visible_regression`
    world = World(api, ws, "rewritten")
    world.cover(PATHS[0])
    world.cover(PATHS[1])
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.cover(PATHS[1], disposition="duplicate")
    world.cover_subsystem("core")
    out["a_semantic_path_rewritten_as_a_valid_completion_is_a_regression"] = {"regressed": close(world, observer)}
    # M7 `test_a_regressed_semantic_set_is_visible_and_never_positive_only`
    world = World(api, ws, "regressed")
    world.cover(PATHS[0])
    world.cover(PATHS[1])
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.uncover(PATHS[1])
    out["a_regressed_semantic_set_is_never_positive_only"] = {"regressed": close(world, observer)}
    # M7 `test_a_completed_audit_is_never_a_low_yield_strike`
    world = World(api, ws, "complete")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    for path in PATHS:
        world.cover(path)
    world.cover_subsystem("core")
    out["a_completed_audit_is_never_a_low_yield_strike"] = {"complete": close(world, observer)}
    # the verdict order and the thresholds
    world = World(api, ws, "threshold")
    observer = world.observer(policy=small(api, minimum_semantic_paths=2))
    observe(world, observer)
    world.cover(PATHS[0])
    out["one_path_below_a_threshold_of_two_is_low_yield"] = case = {"one_path": close(world, observer)}
    world.cover(PATHS[1])
    world.cover(PATHS[2])
    case["two_paths_meet_the_threshold"] = close(world, observer)
    world = World(api, ws, "threshold-evidence")
    observer = world.observer(policy=small(api, minimum_semantic_paths=2))
    observe(world, observer)
    world.cover(PATHS[0])
    world.cover(PATHS[1])
    out["a_gain_equal_to_the_threshold_with_no_new_evidence_is_adequate"] = {"adequate": close(world, observer, evidence=False)}
    world = World(api, ws, "no-gain-no-evidence")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    out["no_gain_and_no_evidence_is_no_evidence"] = case = {"first": close(world, observer, evidence=False)}
    case["second_creates_the_candidate"] = close(world, observer, evidence=False)
    case["reason_code"] = [r["reason_code"] for r in observer.candidates(AUDIT)]
    world = World(api, ws, "mixed-reasons")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    out["a_streak_with_one_evidence_window_has_the_low_yield_reason"] = case = {"no_evidence": close(world, observer, evidence=False)}
    case["low_yield"] = close(world, observer)
    case["reason_code"] = [r["reason_code"] for r in observer.candidates(AUDIT)]
    # remaining work, open questions, observed assets and the completion contract
    world = World(api, ws, "open-question")
    world.partition("p-q", [PATHS[0]], remaining=[], open_questions=["is it real?"])
    observer = world.observer(policy=small(api))
    observe(world, observer)
    for path in PATHS:
        world.cover(path)
    world.cover_subsystem("core")
    out["an_open_question_keeps_the_audit_incomplete"] = {"open": close(world, observer)}
    world = World(api, ws, "pending-asset")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    for path in PATHS:
        world.cover(path)
    world.cover_subsystem("core")
    world.asset("local.bin")
    out["a_pending_observed_asset_keeps_the_audit_incomplete"] = {"pending": close(world, observer)}
    world = World(api, ws, "unresolved-subsystem")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    for path in PATHS:
        world.cover(path)
    world.cover_subsystem("core", tests_not_run=[{"test": "t", "reason": "r", "follow_up": "f"}])
    out["a_subsystem_with_unrun_tests_is_not_covered"] = {"unresolved": close(world, observer)}
    world = World(api, ws, "unavailable")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.cover(PATHS[0], disposition="unavailable")
    world.cover(PATHS[1], disposition="unreviewed")
    out["unavailable_and_unreviewed_are_neither_coverage_nor_semantic"] = {"counted_apart": close(world, observer, evidence=False)}
    world = World(api, ws, "complete-overflow")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    for path in PATHS:
        world.cover(path)
    world.cover_subsystem("core")
    world.settle(5)
    out["a_completed_audit_in_an_overflow_cohort_is_not_comparable"] = {"overflow": observe(world, observer)}
    world = World(api, ws, "complete-unknown")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    for path in PATHS:
        world.cover(path)
    world.cover_subsystem("core")
    world.read()
    ref = world.read(start=1)
    (world.artifacts.root / (ref.partition(":")[2] + ".txt")).write_text("tampered", encoding="utf-8")   # LABELLED damage
    world.settle(2)
    out["unknown_evidence_beats_a_completed_audit"] = {"unknown": observe(world, observer)}
    # the semantic set counts a path once; other audits' rows are not counted
    world = World(api, ws, "semantic-set")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.cover(PATHS[0])
    world.cover(PATHS[0], item="a-second-item-for-the-same-path")
    world.cover(PATHS[1], audit_id="another-audit")
    out["a_path_is_one_semantic_path_however_many_rows_name_it"] = {"closed": close(world, observer)}
    world = World(api, ws, "binary-links")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    for path, disposition in zip(PATHS, ("generated", "duplicate", "binary", "unreviewed")):
        world.cover(path, disposition=disposition)
    out["every_non_semantic_disposition_is_counted_apart"] = {"closed": close(world, observer, evidence=False)}
    return out


# ---- g4 evidence -------------------------------------------------------------------------------------------------------------
class Broken:
    """LABELLED injected fault: the evidence body cannot be read (M7 `Broken`)."""

    @staticmethod
    def document(ref):
        raise OSError("fixture: artifact unavailable " + CANARY)


def g4_evidence(api, ws):
    out = {}
    # M7 `test_unreadable_evidence_is_unknown_never_zero_and_breaks_comparability`
    world = World(api, ws, "unreadable")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    out["unreadable_evidence_is_unknown_never_zero"] = case = {"first": close(world, observer)}
    blind = world.observer(policy=small(api), artifacts=Broken())
    case["unreadable"] = unknown = close(world, blind)
    case["canary_absent"] = CANARY not in json.dumps(unknown)
    case["candidates"] = candidates_view(observer, AUDIT)
    case["the_next_readable_window_still_follows_an_unknown_opening"] = close(world, observer)
    case["then_a_clean_window_counts_again"] = close(world, observer)
    # a real missing and a real modified artifact (M7's own FileArtifacts)
    world = World(api, ws, "missing")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.plant_receipt("r-missing", {"command": ["source-read", PATHS[0], "0"], "output_ref": "sha256:" + "d" * 64})
    world.settle(2)
    out["a_missing_artifact_is_unknown"] = {"missing": observe(world, observer)}
    world = World(api, ws, "modified")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    ref = world.read()
    (world.artifacts.root / (ref.partition(":")[2] + ".txt")).write_text("{}", encoding="utf-8")   # LABELLED damage after the write
    world.settle(2)
    out["a_modified_artifact_is_unknown"] = {"modified": observe(world, observer)}
    world = World(api, ws, "invalid-ref")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.plant_receipt("r-bad", {"command": ["source-read", PATHS[0], "0"], "output_ref": "not-a-reference"})
    world.settle(2)
    out["an_invalid_reference_is_unknown"] = {"invalid": observe(world, observer)}
    world = World(api, ws, "not-json")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.read(text="not json at all")
    world.settle(2)
    out["a_body_that_is_not_json_is_unknown"] = {"body": observe(world, observer)}
    world = World(api, ws, "json-list")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.read(text="[1, 2]")
    world.settle(2)
    out["a_body_that_is_not_an_object_is_unknown"] = {"body": observe(world, observer)}
    # malformed bodies: readable but not understood
    for name, overrides in (("start_line_missing", {"start_line": None}), ("start_line_a_string", {"start_line": "0"}),
                            ("start_line_a_bool", {"start_line": True}), ("next_char_a_float", {"next_char": 1.5}),
                            ("no_identity", {"object_id": None, "path": None}), ("empty_identity", {"object_id": "", "path": ""}),
                            ("identity_not_a_string", {"object_id": 7}), ("path_identity_not_a_string", {"object_id": None, "path": 7}),
                            ("an_empty_object_id_falls_back_to_the_path", {"object_id": ""})):
        world = World(api, ws, "malformed-" + name)
        observer = world.observer(policy=small(api))
        observe(world, observer)
        world.read(text=api.canonical({**world.body(), **overrides}))   # the body is written as given, not rebuilt
        world.settle(2)
        out[("malformed_" + name) if not name.startswith("an_") else name] = case = {"malformed": observe(world, observer)}
        case["windows"] = windows_view(world, observer)
    world = World(api, ws, "path-fallback")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.read(object_id=None)
    world.settle(2)
    out["the_inventory_path_names_a_range_without_an_object_id"] = {"closed": observe(world, observer)}
    world = World(api, ws, "unreadable-and-malformed")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.read(start_line=None)
    world.plant_receipt("r-missing", {"command": ["source-read", PATHS[0], "9"], "output_ref": "sha256:" + "e" * 64})
    world.settle(2)
    out["unreadable_outranks_malformed"] = {"both": observe(world, observer)}
    # distinct ranges (M7 `test_distinct_ranges_come_from_the_real_inert_reader_output_and_repeats_add_nothing`, the part that is
    # this module's: two receipts naming one body, and a different range of the same object)
    world = World(api, ws, "ranges")
    observer = world.observer(policy=small(api))
    ref = world.read(start=0)
    world.plant_receipt("receipt-dup", {"command": ["source-read", PATHS[0], "0"], "output_ref": ref})
    out["two_receipts_of_one_body_are_one_range"] = case = {"baseline_reads_two": observe(world, observer)}
    world.read(start=1)
    case["a_different_range_of_the_same_object_is_new_evidence"] = observe(world, observer)
    world.read(path=PATHS[1], start=0)
    case["another_object_is_new_evidence"] = observe(world, observer)
    world.plant_receipt("receipt-same-range-other-bytes", {"command": ["source-read", PATHS[0], "0"],
                                                           "output_ref": world.artifacts.put(world.api.canonical({**world.body(PATHS[0], 0), "lines": ["other"]}), "x")["ref"]})
    case["the_same_range_with_other_bytes_is_still_one_range"] = observe(world, observer)
    # which receipts count
    world = World(api, ws, "receipt-shapes")
    observer = world.observer(policy=small(api))
    ref = world.read(start=0)
    other_ref = world.artifacts.put(world.api.canonical(world.body(PATHS[1], 0)), "x")["ref"]
    world.plant_receipt("r-other-audit", {"command": ["source-read", PATHS[1], "0"], "output_ref": other_ref}, audit_id="another-audit")
    world.plant_receipt("r-other-command", {"command": ["git", "status"], "output_ref": other_ref})
    world.plant_receipt("r-no-command", {"output_ref": other_ref})
    world.plant_receipt("r-empty-command", {"command": [], "output_ref": other_ref})
    world.plant_receipt("r-none-command", {"command": None, "output_ref": other_ref})
    world.plant_receipt("r-no-output", {"command": ["source-read", PATHS[1], "0"]})
    world.plant_receipt("r-int-output", {"command": ["source-read", PATHS[1], "0"], "output_ref": 5})
    out["only_source_read_receipts_of_this_audit_with_a_string_ref_count"] = {"baseline": observe(world, observer), "ref_used": bool(ref)}
    # M7 `test_state_that_changes_during_evidence_verification_writes_nothing`
    world = World(api, ws, "racing")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.read()
    world.settle(2)
    real = world.artifacts

    class Racing:
        """LABELLED injected race: another execution settles while the evidence is being verified."""

        def __init__(self):
            self.calls = 0

        def document(self, ref):
            self.calls += 1
            world.settle(1)
            return real.document(ref)

    racing = Racing()
    out["state_that_changes_during_evidence_verification_writes_nothing"] = case = {
        "degraded": observe(world, world.observer(policy=small(api), artifacts=racing))}
    case["verifications"] = racing.calls
    case["windows"], case["candidates"] = len(observer.windows(AUDIT)), candidates_view(observer, AUDIT)
    case["state_windows_completed"] = observer.state(AUDIT)["windows_completed"]
    case["the_next_clean_reading_closes_its_window"] = observe(world, observer)
    # a race that changes the audit scope instead of the executions
    world = World(api, ws, "racing-scope")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.read()
    world.settle(2)
    real = world.artifacts

    class Rescoping:
        """LABELLED injected race: a partition appears while the evidence is being verified."""

        def document(self, ref):
            world.partition("p-race", [PATHS[0]])
            return real.document(ref)

    out["a_scope_that_changes_during_verification_writes_nothing"] = {
        "degraded": observe(world, world.observer(policy=small(api), artifacts=Rescoping())), "windows": len(observer.windows(AUDIT))}
    world = World(api, ws, "racing-coverage")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.read()
    world.settle(2)
    real = world.artifacts

    class Covering:
        """LABELLED injected race: a path is dispositioned while the evidence is being verified."""

        def document(self, ref):
            world.cover(PATHS[0])
            return real.document(ref)

    out["coverage_that_changes_during_verification_writes_nothing"] = {
        "degraded": observe(world, world.observer(policy=small(api), artifacts=Covering())), "windows": len(observer.windows(AUDIT))}
    world = World(api, ws, "no-evidence-no-race")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.settle(2)
    out["no_read_evidence_means_no_verification_and_no_race"] = {"closed": observe(world, world.observer(policy=small(api), artifacts=Broken()))}
    return out


# ---- g5 epochs ---------------------------------------------------------------------------------------------------------------
def g5_epochs(api, ws):
    out = {}
    # M7 `test_a_changed_scope_policy_or_release_starts_a_new_epoch_without_comparing_history`
    world = World(api, ws, "epochs")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    first = close(world, observer)
    out["epoch_one_low_window"] = first
    world.partition("p-3", [PATHS[0]])       # the measuring scope changed
    rescoped = close(world, observer)
    out["a_changed_scope_starts_a_new_epoch"] = {"rescoped": rescoped, "epoch_changed": rescoped["epoch"] != first["epoch"],
                                                 "state": state_view(observer),
                                                 "history_is_retained": [w["epoch"] for w in windows_view(world, observer)] == [first["epoch"]]}
    other = close(world, observer)
    moved = observe(world, observer, release="release-2")
    out["a_changed_release_starts_a_new_epoch"] = {"after_rescoping_a_low_window": other, "moved": moved,
                                                   "new_epoch": moved["epoch"] not in {first["epoch"], other["epoch"]}}
    strict = world.observer(policy=small(api, minimum_semantic_paths=2))
    changed_policy = observe(world, strict, release="release-2")
    out["a_changed_policy_starts_a_new_epoch"] = {"strict": changed_policy, "new_epoch": changed_policy["epoch"] != moved["epoch"],
                                                  "state": state_view(strict)}
    revised = observe(world, strict, release="release-2", revision="s" * 40)
    out["a_changed_revision_starts_a_new_epoch"] = {"revised": revised, "new_epoch": revised["epoch"] != changed_policy["epoch"],
                                                    "epochs": state_view(strict)["epochs"]}
    omitted = observe(world, strict, release=None, revision=None)
    out["no_release_and_no_revision_is_an_epoch_too"] = {"omitted": omitted, "new_epoch": omitted["epoch"] != revised["epoch"]}
    # the same epoch is kept across observers and repeated readings
    world = World(api, ws, "same-epoch")
    observer = world.observer(policy=small(api))
    a = observe(world, observer)
    b = observe(world, world.observer(policy=small(api)))
    out["the_same_scope_policy_and_release_stay_in_one_epoch"] = {"first": a, "second": b, "same": a["epoch"] == b["epoch"],
                                                                  "epochs": state_view(observer)["epochs"]}
    # other scope changes: the inventory, the subsystems, the source, a removed partition
    for name, change in (("inventory", lambda w: _replan(w, inventory=lambda inv: inv[:3])),
                         ("subsystems", lambda w: _replan(w, subsystems=lambda s: s + ["extra"])),
                         ("source", lambda w: _replan(w, source=lambda s: {**s, "commit": "c" * 40})),
                         ("a_partition_split", lambda w: (w.partition("p-1", PATHS[:1]))),
                         ("a_partition_subsystem", None)):
        if change is None:
            continue
        world = World(api, ws, "scope-" + name)
        observer = world.observer(policy=small(api))
        before = observe(world, observer)
        change(world)
        after = observe(world, observer)
        out["a_changed_%s_starts_a_new_epoch" % name] = {"before": before, "after": after, "new_epoch": before["epoch"] != after["epoch"]}
    world = World(api, ws, "scope-order")
    observer = world.observer(policy=small(api))
    before = observe(world, observer)
    with world.store.transaction() as tx:
        audit = tx.get("research_audits", AUDIT)
        tx.put("research_audits", AUDIT, {**audit, "inventory": list(reversed(audit["inventory"])), "status": "something-else"})
    after = observe(world, observer)
    out["an_inventory_order_or_a_status_change_is_the_same_epoch"] = {"before": before, "after": after, "same": before["epoch"] == after["epoch"]}
    # a new epoch counts every settled execution into its baseline, keeps the old windows and candidate
    world = World(api, ws, "new-epoch-history")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    close(world, observer)
    closed = close(world, observer)
    old_candidates = candidates_view(observer, AUDIT)
    world.partition("p-9", [PATHS[0]])
    world.settle(3)
    out["a_new_epoch_keeps_the_old_windows_and_candidate_and_counts_history_into_its_baseline"] = case = {
        "old_epoch_candidate_created": closed["candidate_created"], "new_baseline": observe(world, observer),
        "state": state_view(observer), "windows_epochs": [w["epoch"] for w in windows_view(world, observer)],
        "candidates_are_unchanged": candidates_view(observer, AUDIT) == old_candidates, "streak_restarts": observer.state(AUDIT)["streak"]}
    case["the_next_window_is_a_new_epoch_window"] = close(world, observer)
    case["window_epochs_then"] = sorted({w["epoch"] for w in windows_view(world, observer)})
    case["windows_indexes"] = [(w["epoch"], w["index"]) for w in windows_view(world, observer)]
    return out


def _replan(world, inventory=None, subsystems=None, source=None):
    """LABELLED. A changed audit row (a re-imported inventory, subsystem list or source): planted in place."""
    with world.store.transaction() as tx:
        audit = tx.get("research_audits", AUDIT)
        if inventory is not None:
            audit = {**audit, "inventory": inventory(audit["inventory"])}
        if subsystems is not None:
            audit = {**audit, "subsystems": subsystems(audit["subsystems"])}
        if source is not None:
            audit = {**audit, "source": source(audit["source"])}
        tx.put("research_audits", AUDIT, audit)


# ---- g6 candidates -----------------------------------------------------------------------------------------------------------
def two_low_windows(api, world, policy=None):
    observer = world.observer(policy=policy)
    observe(world, observer)
    size = (policy or api.packaged_policy())["window_executions"]
    close(world, observer, executions=size)
    return close(world, observer, executions=size), observer


def g6_candidates(api, ws):
    out = {}
    # M7 `test_two_low_windows_create_one_research_required_candidate_with_no_job_membership`
    world = World(api, ws, "candidate")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    out["two_low_windows_create_one_candidate_and_a_third_tick_writes_no_window_and_no_candidate"] = case = {"first": close(world, observer)}
    case["second"] = second = close(world, observer)
    case["third_tick_in_the_same_window"] = tick = observe(world, observer)
    # M7 `_record` rewrites the epoch STATE row (`last_observation`, `updated_at`) on every observation; the window receipts and
    # the candidate row are what a repeated tick never writes
    case["third_tick_writes_no_window_and_no_candidate"] = {
        "changed": tick["changed"], "windows_digest_unchanged": tick["before"][world.api.BUCKET_WINDOWS] == tick["after"][world.api.BUCKET_WINDOWS],
        "candidate_digest_unchanged": tick["before"][world.api.BUCKET_INVESTIGATIONS] == tick["after"][world.api.BUCKET_INVESTIGATIONS]}
    case["candidates"] = candidates_view(observer, AUDIT)
    row = observer.candidates(AUDIT)[0]
    case["row_id_is_the_candidate_identity"] = row["id"] == api.candidate_identity(second["epoch"])
    case["row_has_no_job_membership"] = "job_ids" not in row and "family_status" not in row
    case["row_policy_is_the_digest_of_the_validated_policy"] = row["policy_sha256"] == api.policy_digest(api.validate_policy(small(api)))
    case["row_is_in_the_owners_undecided_state"] = row["state"] == api.RESEARCH_REQUIRED
    case["row_windows_are_the_windows"] = row["windows"] == [w["id"] for w in observer.windows(AUDIT)]
    case["row"] = {k: row[k] for k in ("trust", "authority", "evidence_refs", "decided_at", "count")}
    case["third_low_window_deduplicates_onto_the_row"] = third = close(world, observer)
    case["after_the_third"] = candidates_view(observer, AUDIT)
    case["third_candidate_is_the_same_row"] = third["candidate"] == short(row["id"]) and third["candidate_created"] is False
    case["fourth_low_window"] = close(world, observer)
    case["after_the_fourth"] = candidates_view(observer, AUDIT)
    # a later observation of the same window is replaced, not appended
    # M7 `test_an_owner_disposition_survives_later_observations`
    world = World(api, ws, "owner")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    close(world, observer)
    closed = close(world, observer)
    candidate = observer.candidates(AUDIT)[0]["id"]
    owner = api.Portfolio(world.store, definitions(), clock=lambda: "2028-02-01T00:00:00+00:00")
    decided = owner.disposition(candidate, "deferred", ["docs/zeus/evidence.md"])["candidate"]
    out["an_owner_disposition_survives_later_observations"] = case = {
        "created": closed["candidate_created"], "decided": {k: decided[k] for k in ("state", "kind", "decided_at", "evidence_refs")},
        "next_low_window": close(world, observer), "kept": candidates_view(observer, AUDIT)}
    # M7 `test_a_progress_candidate_is_never_a_failed_job_family_anywhere`, the row this module wrote
    world = World(api, ws, "job-family")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    close(world, observer)
    close(world, observer)
    with world.store.transaction() as tx:
        rows = tx.scan(api.BUCKET_INVESTIGATIONS)
    out["the_candidate_row_carries_the_audit_progress_kind_and_no_job_family"] = {
        "rows": len(rows), "kind": rows[0]["kind"], "kind_is_the_explicit_audit_progress_kind": rows[0]["kind"] == api.KIND,
        "job_ids_absent": "job_ids" not in rows[0], "family_status_absent": "family_status" not in rows[0],
        "key_set": sorted(rows[0]), "observations": rows[0]["observations"], "evidence_refs": rows[0]["evidence_refs"]}
    # the streak and the durable receipts disagree: report the streak, record no candidate
    world = World(api, ws, "disagree")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    close(world, observer)
    with world.store.transaction() as tx:       # LABELLED planted fault: the first window's receipt is gone
        tx.data.pop((api.BUCKET_WINDOWS, observer.windows(AUDIT)[0]["id"]), None)
    out["a_streak_with_a_missing_window_receipt_records_no_candidate"] = case = {"second_low_window": close(world, observer)}
    case["candidates"] = candidates_view(observer, AUDIT)
    case["state"] = state_view(observer)
    case["a_later_window_with_both_receipts_present_creates_it"] = close(world, observer)
    case["candidates_then"] = candidates_view(observer, AUDIT)
    world = World(api, ws, "noncontiguous")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    close(world, observer)
    close(world, observer)                      # windows 1 and 2 are low, the candidate exists
    close(world, observer)
    row = observer.candidates(AUDIT)[0]
    out["a_later_streak_of_the_same_epoch_never_creates_a_second_candidate"] = {
        "candidates": len(observer.candidates(AUDIT)), "same_windows": row["windows"] == [w["id"] for w in observer.windows(AUDIT)[:2]]}
    world = World(api, ws, "gap")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    close(world, observer)                      # window 1 low
    world.cover(PATHS[0])
    close(world, observer)                      # window 2 adequate
    close(world, observer, evidence=False)      # window 3 low (streak 1)
    with world.store.transaction() as tx:       # LABELLED planted fault: window 3's receipt is gone
        tx.data.pop((api.BUCKET_WINDOWS, observer.windows(AUDIT)[2]["id"]), None)
    out["low_windows_that_are_not_contiguous_record_no_candidate"] = case = {"window_four": close(world, observer, evidence=False)}
    case["candidates"] = candidates_view(observer, AUDIT)
    case["low_windows_left"] = [w["index"] for w in observer.windows(AUDIT) if w["verdict"] != "adequate_progress"]
    # an unknown or overflowed window is never part of a candidate
    world = World(api, ws, "unknown-never-counts")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    close(world, observer)
    out["a_not_comparable_window_between_low_windows_clears_the_streak"] = case = {}
    world.settle(5)
    case["overflow"] = observe(world, observer)
    case["low_after"] = close(world, observer)
    case["candidates"] = candidates_view(observer, AUDIT)
    # the packaged policy (M7 `test_two_low_windows_route_through_...`, the part that is this module's: the thresholds in force)
    world = World(api, ws, "packaged-candidate")
    closed, observer = two_low_windows(api, world)
    out["two_low_windows_under_the_packaged_policy"] = {
        "closed": closed, "windows": [w["executions"] for w in observer.windows(AUDIT)],
        "candidates": candidates_view(observer, AUDIT),
        "policy_is_the_packaged_one": observer.candidates(AUDIT)[0]["policy_sha256"] == api.policy_digest(api.validate_policy(api.packaged_policy())),
        "scope_is_the_audit_epoch_and_policy": sorted(observer.candidates(AUDIT)[0]["epoch_scope"]),
        "candidate_label": api.candidate_label(observer.candidates(AUDIT)[0]["id"])}
    # the rows `candidates()` returns
    world = World(api, ws, "kinds")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    close(world, observer)
    close(world, observer)
    with world.store.transaction() as tx:       # LABELLED planted rows of other kinds and audits
        tx.put(api.BUCKET_INVESTIGATIONS, "legacy-family", {"id": "legacy-family", "state": api.RESEARCH_REQUIRED, "job_ids": ["j1"]})
        tx.put(api.BUCKET_INVESTIGATIONS, "other-audit", {"id": "other-audit", "kind": api.KIND, "audit_id": "another-audit",
                                                           "state": api.RESEARCH_REQUIRED})
        tx.put(api.BUCKET_INVESTIGATIONS, "other-kind", {"id": "other-kind", "kind": "something_else", "audit_id": AUDIT})
    out["candidates_are_the_audit_progress_rows_of_the_audit"] = {
        "for_the_audit": [r["id"][:12] for r in observer.candidates(AUDIT)],
        "all_audits": sorted(r["id"][:12] for r in observer.candidates()),
        "none_for_an_unknown_audit": observer.candidates("no-such-audit"), "legacy_rows_in_the_bucket": 3}
    # eligibility: the domain rule over the rows this module wrote (the research program's call, labelled)
    world = World(api, ws, "eligible")
    closed, observer = two_low_windows(api, world, policy=small(api))
    out["eligibility_over_the_rows_this_module_wrote"] = eligibility(api, world, observer, small(api))
    return out


def eligibility(api, world, observer, policy):
    """M7 `test_a_disallowed_audit_a_decided_owner_and_a_changed_epoch_are_all_ineligible` and `test_a_discovery_item_cannot_forge_a_progress_
    candidate_and_one_claim_wins` (the rule `eligible_candidates`, the ResearchProgram's caller is another family): the counts the rule
    returns over the rows `AuditProgress` wrote, with each exclusion made by a LABELLED edit of the row."""
    digest = api.policy_digest(api.validate_policy(policy))
    rows = observer.candidates(AUDIT)
    windows = observer.windows(AUDIT)
    with world.store.transaction() as tx:
        states = tx.scan(api.BUCKET_STATE)

    def counts(candidates=rows, audits=(AUDIT,), claimed=(), required=None, policy_sha=digest, windows_=windows, states_=states):
        found = api.eligible_candidates(candidates=candidates, windows=windows_, states=states_,
                                        source={"topic": "storage", "audit_ids": list(audits)}, claimed=set(claimed),
                                        required_state=required or api.RESEARCH_REQUIRED, policy_sha256=policy_sha)
        return {"counts": found["counts"], "eligible": [e["candidate"]["id"][:12] for e in found["candidates"]],
                "windows": [[w["index"] for w in e["windows"]] for e in found["candidates"]]}
    row = rows[0]
    out = {"eligible": counts()}
    out["audit_not_authorized"] = counts(audits=("another-audit",))
    out["decided_by_the_owner"] = counts(candidates=[{**row, "state": "researched"}])
    out["a_changed_epoch"] = counts(candidates=[{**row, "epoch": "e" * 64}])
    out["a_window_whose_membership_no_longer_matches"] = counts(candidates=[{**row, "window_sha256": ["0" * 64, "0" * 64]}])
    out["a_policy_no_longer_in_force"] = counts(candidates=[{**row, "policy_sha256": "0" * 64}])
    out["another_policy_in_force"] = counts(policy_sha="1" * 64)
    out["claimed_by_another_program"] = counts(claimed=[row["id"]])
    out["malformed_reason_code"] = counts(candidates=[{**row, "reason_code": "stalled"}])
    out["malformed_no_windows"] = counts(candidates=[{**row, "windows": []}])
    out["malformed_identifier"] = counts(candidates=[{**row, "id": "not a valid id!"}])
    out["a_missing_window_receipt"] = counts(windows_=windows[:1])
    out["a_window_that_is_no_longer_low"] = counts(windows_=[{**windows[0], "verdict": "adequate_progress"}, windows[1]])
    out["a_window_that_is_not_comparable"] = counts(windows_=[{**windows[0], "comparable": False}, windows[1]])
    out["no_state_for_the_audit"] = counts(states_=[])
    out["another_kind_is_not_scanned"] = counts(candidates=[{**row, "kind": "failure_family"}])
    return out


# ---- g7 degraded and status --------------------------------------------------------------------------------------------------
def faulting(api, world, on):
    """LABELLED. An injected store failure on one `MemoryTransaction` operation (`on`: 'get'/'scan'/'put' with a bucket)."""
    transaction = api.MemoryTransaction
    original = getattr(transaction, on[0])

    def failing(self, bucket, *args):
        if bucket == on[1]:
            raise StoreFault("injected store failure")
        return original(self, bucket, *args)

    class Patch:
        def __enter__(self):
            setattr(transaction, on[0], failing)

        def __exit__(self, *exc):
            setattr(transaction, on[0], original)
    return Patch()


def g7_degraded_status(api, ws):
    out = {}
    # M7 `test_an_unknown_or_unpartitioned_audit_is_degraded_and_never_a_known_zero`
    world = World(api, ws, "unknown")
    observer = world.observer(policy=small(api))
    out["an_unknown_audit_is_degraded_with_no_write"] = case = {"missing": observe(world, observer, audit_id="no-such-audit")}
    case["state_rows"], case["window_rows"] = len(scan(world, api.BUCKET_STATE)), len(scan(world, api.BUCKET_WINDOWS))
    case["degraded_keys_are_the_fixed_shape"] = sorted(case["missing"]["keys"])
    case["audit_id_is_echoed_not_normalised"] = observe(world, observer, audit_id="")["reason_code"]
    with world.store.transaction() as tx:
        for row in tx.scan("research_partitions"):
            tx.data.pop(("research_partitions", row["partition_id"]), None)
    out["an_unpartitioned_audit_is_degraded_with_no_write"] = {"bare": observe(world, observer), "state": observer.state(AUDIT)}
    world = World(api, ws, "partitions-of-another-audit", partitions=False)
    world.partition("p-x", PATHS[:1])
    with world.store.transaction() as tx:
        row = tx.get("research_partitions", "p-x")
        tx.put("research_partitions", "p-x", {**row, "audit_id": "another-audit"})
    out["partitions_of_another_audit_do_not_make_this_one_partitioned"] = {"bare": observe(world, world.observer(policy=small(api)))}
    world = World(api, ws, "audit-row-shapes")
    observer = world.observer(policy=small(api))
    for name, body in (("list", ["not", "an", "audit"]), ("string", "audit"), ("none", None), ("number", 3)):
        world.put("research_audits", "shape-" + name, body)
        out["an_audit_row_that_is_a_%s_is_unknown" % name] = observe(world, observer, audit_id="shape-" + name)
    world.put("research_audits", "no-id", {"version": 1, "inventory": [], "subsystems": []})
    world.partition("p-no-id", [])
    with world.store.transaction() as tx:
        row = tx.get("research_partitions", "p-no-id")
        tx.put("research_partitions", "p-no-id", {**row, "audit_id": "no-id"})
    out["an_audit_row_without_an_id_is_an_observation_failure"] = observe(world, observer, audit_id="no-id")
    # a malformed stored record is degraded rather than a known zero (the existing authority raises)
    for name, plant in (
            ("a_path_row_with_an_unknown_disposition", lambda w: w.put("research_paths", "bad-1", {"audit_id": AUDIT, "record": {
                **asdict(w.api.PathDisposition(PATHS[0], "semantic", ["sha256:" + "1" * 64], [], "j", [], "read", [])), "disposition": "bogus"}})),
            ("a_path_row_without_a_record_shape", lambda w: w.put("research_paths", "bad-2", {"audit_id": AUDIT, "record": {"path": PATHS[0]}})),
            ("a_path_row_without_an_audit_id", lambda w: w.put("research_paths", "bad-3", {"record": {}})),
            ("a_subsystem_row_without_a_record_shape", lambda w: w.put("research_subsystems", "bad-4", {"audit_id": AUDIT, "record": {"name": "x"}})),
            ("an_observed_asset_in_an_unknown_state", lambda w: w.put("research_observed_assets", "bad-5", {"audit_id": AUDIT, "record": {
                **asdict(w.api.ObservedAsset(AC.b64(b"x.bin"), "observed", "unreviewed_observed_asset", None, None, [])), "state": "bogus"}})),
            ("a_partition_row_without_an_audit_id", lambda w: w.put("research_partitions", "bad-6", {"partition_id": "bad-6"})),
            ("a_partition_row_without_a_partition_id", lambda w: w.put("research_partitions", "bad-7", {"audit_id": AUDIT})),
            ("a_receipt_row_without_a_receipt", lambda w: w.put("research_receipts", "bad-8", {"audit_id": AUDIT})),
            ("a_receipt_row_whose_receipt_is_not_a_dict", lambda w: w.put("research_receipts", "bad-9", {"audit_id": AUDIT, "receipt": "r"})),
            ("a_task_row_that_is_not_a_dict", lambda w: w.put("tasks", "bad-10", "not a task")),
            ("a_task_row_with_a_string_details", lambda w: w.put("tasks", "bad-11", {"id": "t", "status": "succeeded",
                                                                                      "message": {"what": {"details": "x"}}}))):
        world = World(api, ws, "malformed-" + name)
        observer = world.observer(policy=small(api))
        before_baseline = observe(world, observer)
        plant(world)
        out["malformed_" + name] = {"baseline_before_the_plant": before_baseline["status"], "observation": observe(world, observer),
                                    "state_after": state_view(observer)}
    # a store fault is degraded too and writes nothing (M7 `observe` catches every Exception)
    world = World(api, ws, "fault")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.settle(2)
    with faulting(api, world, ("scan", "tasks")):
        out["a_store_read_fault_is_degraded_and_writes_nothing"] = observe(world, observer)
    with faulting(api, world, ("put", api.BUCKET_STATE)):
        out["a_store_write_fault_is_degraded_and_commits_nothing"] = observe(world, observer)
    with faulting(api, world, ("put", api.BUCKET_WINDOWS)):
        out["a_window_write_fault_commits_neither_the_window_nor_the_state"] = case = {"observation": observe(world, observer)}
        case["windows"] = len(observer.windows(AUDIT))
    case["the_next_reading_closes_the_window"] = observe(world, observer)
    world = World(api, ws, "candidate-write-fault")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    close(world, observer)
    with faulting(api, world, ("put", api.BUCKET_INVESTIGATIONS)):
        out["a_candidate_write_fault_commits_nothing_of_the_window"] = case = {"observation": close(world, observer)}
    case["state"] = state_view(observer)
    case["windows"] = len(observer.windows(AUDIT))
    case["recovers"] = observe(world, observer)
    # a clock that is not a timestamp: `_seconds` is None (the `except (TypeError, ValueError)` of `_seconds`)
    for name, bad in (("a_string", "not-a-time"), ("none", None), ("a_number", 12)):
        world = World(api, ws, "clock-" + name)
        good = world.clock()
        state = {"calls": 0}

        def clock(good=good, bad=bad, state=state):
            state["calls"] += 1
            return good() if state["calls"] == 1 else bad

        observer = world.observer(policy=small(api), clock=clock)
        observe(world, observer)
        out["a_clock_returning_%s_makes_the_elapsed_seconds_unknown" % name] = case = {"closed": close(world, observer)}
        case["windows"] = windows_view(world, observer)
        case["state_updated_at"] = observer.state(AUDIT)["updated_at"]
    world = World(api, ws, "clock-fault")
    observer = world.observer(policy=small(api), clock=lambda: (_ for _ in ()).throw(StoreFault("clock failed")))
    # `observe` reports the failure through `_degraded`, which reads the same clock again: the second raise is not caught
    out["a_clock_that_raises_escapes_observe_through_degraded"] = call(world, observer.observe, AUDIT, release_id="release-1", revision=REV)
    world = World(api, ws, "clock-iso-offset")
    seq = iter(["2028-01-01T00:00:00+00:00", "2028-01-01T01:30:00.500000+01:00", "2028-01-01T03:00:00+00:00"])
    observer = world.observer(policy=small(api), clock=lambda: next(seq))
    observe(world, observer)
    out["elapsed_seconds_come_from_the_clock_readings_across_offsets"] = case = {"closed": close(world, observer)}
    case["windows"] = windows_view(world, observer)
    world = World(api, ws, "default-clock")
    observer = api.AuditProgress(world.store, world.artifacts, policy=small(api))
    out["the_default_clock_is_the_harness_utcnow"] = {"baseline": observe(world, observer), "state_created_at": observer.state(AUDIT)["created_at"]}
    # `status_view`
    world = World(api, ws, "status")
    observer = world.observer(policy=small(api))
    out["status_view_of_nothing"] = {"none": api.status_view(None), "empty_dict_is_observed": api.status_view({}), "a_list": api.status_view([]),
                                     "a_string": api.status_view("state"), "state_before_any_observation": api.status_view(observer.state(AUDIT)),
                                     "observer_state_is_none": observer.state(AUDIT)}
    observe(world, observer)
    out["status_view_after_the_baseline"] = api.status_view(observer.state(AUDIT))
    world.settle(1)
    observe(world, observer)
    out["status_view_after_an_observation_with_no_window"] = status_trim(api.status_view(observer.state(AUDIT)))
    close(world, observer, executions=1)
    out["status_view_after_a_low_window_with_no_semantic_credit"] = status_trim(api.status_view(observer.state(AUDIT)))
    close(world, observer)
    out["status_view_after_the_candidate"] = status_trim(api.status_view(observer.state(AUDIT)))
    world.cover(PATHS[0])
    close(world, observer)
    out["status_view_after_real_progress"] = status_trim(api.status_view(observer.state(AUDIT)))
    out["status_view_keys"] = sorted(api.status_view(observer.state(AUDIT)))
    out["status_view_does_not_alias_the_state"] = {"state_unchanged": api.status_view(observer.state(AUDIT)) == api.status_view(observer.state(AUDIT))}
    # M7 `test_the_service_takes_a_baseline_before_admission_and_observes_every_settlement`, the part that is `status_view`/`state`
    world = World(api, ws, "status-service")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    world.settle(1)
    observe(world, observer)
    world.settle(1)
    observe(world, observer)
    view_ = api.status_view(observer.state(AUDIT))
    out["status_view_of_a_window_with_no_gain"] = {"observed": view_["observed"], "windows_completed": view_["windows_completed"],
                                                  "last_status": view_["last_observation"]["status"], "last_delta": view_["last_delta"],
                                                  "streak": view_["streak"], "candidate": view_["candidate"], "last_verdict": view_["last_verdict"],
                                                  "metrics": view_["metrics"], "baseline_executions": observer.state(AUDIT)["baseline"]["executions"],
                                                  "windows_executions": [w["executions"] for w in observer.windows(AUDIT)]}
    # read-only reads
    world = World(api, ws, "reads")
    observer = world.observer(policy=small(api))
    observe(world, observer)
    close(world, observer)
    world.partition("p-r", [PATHS[0]])
    observe(world, observer)
    close(world, observer)
    world.partition("p-r2", [PATHS[1]])
    observe(world, observer)
    close(world, observer)
    before = snap(world)
    out["windows_are_sorted_by_epoch_then_index_and_the_reads_write_nothing"] = {
        "windows": [(short(w["epoch"]), w["index"]) for w in observer.windows(AUDIT)],
        "sorted_by_epoch_then_index": [(w["epoch"], w["index"]) for w in observer.windows(AUDIT)] ==
                                      sorted((w["epoch"], w["index"]) for w in observer.windows(AUDIT)),
        "windows_of_another_audit": observer.windows("no-such-audit"), "state_of_another_audit": observer.state("no-such-audit"),
        "unchanged": snap(world) == before}
    return out


def status_trim(view_):
    return {k: v for k, v in view_.items() if k not in ("updated_at",)}


# ---- g8 rows written by the owners -------------------------------------------------------------------------------------------
def g8_owner_rows(api, ws):
    out = {}
    env = AC.build(api, ws, "owner-rows")
    audit_id = env.record["id"]
    world = SimpleNamespace(api=api, store=env.store, audit_id=audit_id)
    observer = api.AuditProgress(env.store, env.artifacts, policy=small(api, window_executions=1), clock=tick_clock(api))
    out["an_imported_audit_with_no_partition_is_not_partitioned"] = observe(world, observer, audit_id=audit_id)
    parts = env.service.partition(audit_id, 1)
    out["the_baseline_over_the_real_import_and_partitions"] = observe(world, observer, audit_id=audit_id)
    part, task = AC.assigned(env, "paths", generation=True)
    ref = AC.evidence(env, "observed implementation and callers")
    disposition = AC.path_disposition(env, part["paths"][0], "semantic", ref, justification="implementation traced")
    checkpoint = AC.cp(env, part, evidence_refs=[ref], remaining_paths=[], cursor="next")
    env.service.checkpoint(task, checkpoint, [disposition], [], None)
    out["a_claimed_task_is_live_work"] = observe(world, observer, audit_id=audit_id)
    completed = env.workflow.complete(task, {"analysis": {"outcome": "analyzed"}})["status"]
    out["a_completed_task_closes_the_window_with_the_real_checkpoint_gain"] = case = {"completed": completed,
                                                                                    "closed": observe(world, observer, audit_id=audit_id)}
    case["windows"] = [{"verdict": w["verdict"], "executions": w["executions"], "members": [m.split(":", 1)[1] for m in w["members"]],
                        "delta": w["delta"]} for w in observer.windows(audit_id)]
    case["state"] = state_view(observer, audit_id)
    case["real_partition_count"] = len(parts)
    coverage = env.service.coverage(audit_id)
    case["the_audit_authority_agrees"] = {"reviewed_paths": coverage["reviewed_paths"], "remaining_paths": len(coverage["remaining_paths"]),
                                          "whole_analysis_complete": coverage["whole_analysis_complete"]}
    case["metrics_agree_with_the_authority"] = case["closed"]["metrics"]["remaining_paths"] == len(coverage["remaining_paths"])
    out["the_progress_buckets_are_the_only_rows_written"] = {"authority_unchanged_across_the_close": case["closed"]["authority_unchanged"],
                                                             "changed": case["closed"]["changed"]}
    return out


def tick_clock(api):
    def tick():
        api.advance(STEP_SECONDS)
        return api.utcnow()
    return tick


# ---- coverage ----------------------------------------------------------------------------------------------------------------
G1, G2, G3, G4, G5, G6, G7, G8 = ("g1_policy.", "g2_windows.", "g3_yield.", "g4_evidence.", "g5_epochs.", "g6_candidates.",
                                  "g7_degraded_status.", "g8_owner_rows.")


def at(prefix, *names):
    return [prefix + n for n in names]


def unreachable(why):
    return {"unreachable": why}


# Every `raise` of M7 `application/audit_progress.py` @ e38aa722 (2), every `except` branch of it (4: L77, L168, L186, L188) and
# its `require`s (none: the module calls `require` nowhere), keyed by source line: the cases that reach it. A pointer is checked
# at run time (a pointer that does not resolve is a driver error).
RAISES = {
    "105 raise ProgressRefused('unknown_audit')": at(G7, "an_unknown_audit_is_degraded_with_no_write", "an_audit_row_that_is_a_list_is_unknown",
                                                     "an_audit_row_that_is_a_string_is_unknown", "an_audit_row_that_is_a_none_is_unknown",
                                                     "an_audit_row_that_is_a_number_is_unknown"),
    "109 raise ProgressRefused('audit_not_partitioned')": at(G7, "an_unpartitioned_audit_is_degraded_with_no_write",
                                                             "partitions_of_another_audit_do_not_make_this_one_partitioned") + at(
        G8, "an_imported_audit_with_no_partition_is_not_partitioned"),
}
EXCEPTS = {
    "77 except (TypeError, ValueError) in _seconds": at(G7, "a_clock_returning_a_string_makes_the_elapsed_seconds_unknown",
                                                         "a_clock_returning_none_makes_the_elapsed_seconds_unknown",
                                                         "a_clock_returning_a_number_makes_the_elapsed_seconds_unknown"),
    "168 except Exception in _evidence": at(G4, "unreadable_evidence_is_unknown_never_zero", "a_missing_artifact_is_unknown",
                                            "a_modified_artifact_is_unknown", "an_invalid_reference_is_unknown",
                                            "a_body_that_is_not_json_is_unknown", "a_body_that_is_not_an_object_is_unknown"),
    "186 except ProgressRefused in observe": at(G7, "an_unknown_audit_is_degraded_with_no_write", "an_unpartitioned_audit_is_degraded_with_no_write"),
    "188 except Exception in observe": at(G7, "an_audit_row_without_an_id_is_an_observation_failure",
                                          "malformed_a_path_row_with_an_unknown_disposition", "malformed_a_path_row_without_a_record_shape",
                                          "malformed_a_subsystem_row_without_a_record_shape", "malformed_an_observed_asset_in_an_unknown_state",
                                          "a_store_read_fault_is_degraded_and_writes_nothing", "a_store_write_fault_is_degraded_and_commits_nothing",
                                          "a_window_write_fault_commits_neither_the_window_nor_the_state",
                                          "a_candidate_write_fault_commits_nothing_of_the_window", "a_clock_that_raises_escapes_observe_through_degraded"),
}
REQUIRES = {"none": "the module calls `require` nowhere (grep of the SOURCE file: 0 matches); the refusals of the existing audit "
                    "authority (`ResearchAudits._coverage`/`_observed`, whose `require`s belong to `research.audit_core`) reach this module only as "
                    "the `except Exception` of `observe`, covered above"}
RAISE_UNREACHABLE = {}   # every raise and every except branch has a case; nothing is unreachable


def other(module, *cases):
    """A test whose subject (or part of it) is another module: the cases of the part this module decides, if any."""
    return {"other family": module, **({"cases": list(cases)} if cases else {})}


M7_TESTS = {   # tests/test_audit_progress.py @ e38aa722: 28 test functions
    "test_the_packaged_policy_is_validated_and_a_broken_one_is_refused_not_defaulted": at(
        G1, "packaged_policy_resource", "default_policy_is_the_validated_packaged_one", "broken_window_executions_zero",
        "broken_low_yield_windows_one", "broken_minimum_semantic_paths_bool", "broken_version_two", "broken_extra_field", "broken_other_schema"),
    "test_the_audit_progress_source_is_opt_in_bounded_and_keeps_the_legacy_config_identical": other(
        "research.program_records (validate_config, the ResearchProgram configuration)") | {
        "cases": at(G1, "source_valid", "source_null", "source_missing_topic", "source_empty_audit_ids", "source_wildcard", "source_duplicate",
                    "source_extra_field")},
    "test_the_baseline_excludes_history_and_exactly_one_window_closes_per_reading": at(G2, "baseline_excludes_history"),
    "test_new_evidence_without_semantic_gain_is_low_yield_and_real_progress_clears_the_streak": at(G3, "low_yield_then_adequate_then_no_evidence"),
    "test_generated_duplicate_and_binary_completions_are_valid_but_never_semantic_gain": at(G3, "generated_duplicate_and_binary_are_never_semantic_gain"),
    "test_one_semantic_path_clears_the_streak_and_a_subsystem_only_gain_does_not": at(G3, "one_semantic_path_clears_and_a_subsystem_only_gain_does_not"),
    "test_a_semantic_path_rewritten_as_a_valid_completion_is_a_visible_regression": at(G3, "a_semantic_path_rewritten_as_a_valid_completion_is_a_regression"),
    "test_a_regressed_semantic_set_is_visible_and_never_positive_only": at(G3, "a_regressed_semantic_set_is_never_positive_only"),
    "test_a_completed_audit_is_never_a_low_yield_strike": at(G3, "a_completed_audit_is_never_a_low_yield_strike"),
    "test_unreadable_evidence_is_unknown_never_zero_and_breaks_comparability": at(G4, "unreadable_evidence_is_unknown_never_zero"),
    "test_a_nondivisible_overflow_cohort_is_consumed_once_and_leaves_nothing_behind": at(G2, "overflow_nondivisible"),
    "test_gains_before_a_divisible_overflow_anchor_the_next_window_and_invent_no_strike": at(G2, "overflow_divisible_anchors_the_next_window"),
    "test_two_low_windows_create_one_research_required_candidate_with_no_job_membership": at(
        G6, "two_low_windows_create_one_candidate_and_a_third_tick_writes_no_window_and_no_candidate"),
    "test_an_owner_disposition_survives_later_observations": at(G6, "an_owner_disposition_survives_later_observations"),
    "test_duplicate_ticks_live_work_and_a_restart_do_not_create_extra_windows_or_strikes": at(G2, "duplicate_ticks_live_work_and_restart"),
    "test_a_changed_scope_policy_or_release_starts_a_new_epoch_without_comparing_history": at(
        G5, "a_changed_scope_starts_a_new_epoch", "a_changed_release_starts_a_new_epoch", "a_changed_policy_starts_a_new_epoch"),
    "test_state_that_changes_during_evidence_verification_writes_nothing": at(G4, "state_that_changes_during_evidence_verification_writes_nothing"),
    "test_an_unknown_or_unpartitioned_audit_is_degraded_and_never_a_known_zero": at(
        G7, "an_unknown_audit_is_degraded_with_no_write", "an_unpartitioned_audit_is_degraded_with_no_write"),
    "test_distinct_ranges_come_from_the_real_inert_reader_output_and_repeats_add_nothing": other(
        "adapters.audit_runner (the real inert reader and the real Git audit fixture)") | {
        "cases": at(G4, "two_receipts_of_one_body_are_one_range")},
    "test_a_progress_candidate_is_never_a_failed_job_family_anywhere": other(
        "intake.portfolio (Portfolio.status) and research.dge (eligible_investigations, the failure-family rule)") | {
        "cases": at(G6, "the_candidate_row_carries_the_audit_progress_kind_and_no_job_family")},
    "test_two_low_windows_route_through_the_existing_claim_capture_and_council": other(
        "research.program_tick, research.dispatch_recovery (ResearchProgram claim, capture and council)") | {
        "cases": at(G6, "two_low_windows_under_the_packaged_policy")},
    "test_a_disallowed_audit_a_decided_owner_and_a_changed_epoch_are_all_ineligible": other(
        "research.program_tick (the ResearchProgram tick that calls the rule)") | {
        "cases": at(G6, "eligibility_over_the_rows_this_module_wrote")},
    "test_a_discovery_item_cannot_forge_a_progress_candidate_and_one_claim_wins": other(
        "research.program_records, research.dispatch_recovery (forged discovery item, the dispatch claim)") | {
        "cases": at(G6, "eligibility_over_the_rows_this_module_wrote")},
    "test_the_service_takes_a_baseline_before_admission_and_observes_every_settlement": other(
        "adapters.audit_service (AuditServiceRunner, the service `status` command)") | {
        "cases": at(G7, "status_view_of_a_window_with_no_gain")},
    "test_an_observation_failure_is_degraded_beside_an_unchanged_execution_result": other("adapters.audit_service (the runner's observer-failure result)"),
    "test_the_production_wiring_gives_the_runner_a_real_observer_on_the_same_store": other("adapters.audit_service (build_runner)") | {
        "cases": at(G1, "default_policy_is_the_validated_packaged_one")},
    "test_the_progress_observations_are_declared_events_with_identifiers_and_codes": other("adapters.audit_service, domain.observation (declared events)"),
    "test_the_progress_facts_are_allow_listed_and_a_foreign_observation_is_never_a_zeus_code": other("adapters.audit_service (progress_facts)"),
}


def resolve(result, path):
    node = result
    for part in path.split("."):
        node = node[part]   # a pointer that does not resolve is a driver error, never a silent gap
    return node


def pointers(entry):
    return entry if isinstance(entry, list) else entry.get("cases", [])


def coverage(result) -> dict:
    tables = (RAISES, EXCEPTS, M7_TESTS)
    for table in tables:
        for entry in table.values():
            for pointer in pointers(entry):
                resolve(result, pointer)
    other_family = {name: entry["other family"] for name, entry in M7_TESTS.items() if isinstance(entry, dict)}
    mirrored = sorted(name for name, entry in M7_TESTS.items() if pointers(entry))
    return {"raises": RAISES, "excepts": EXCEPTS, "requires": REQUIRES, "unreachable": RAISE_UNREACHABLE,
            "m7_test_audit_progress": M7_TESTS, "other_family": other_family, "mirrored_node_ids": mirrored,
            "counts": {"raise_sites_in_the_module": 2, "except_branches_in_the_module": 4, "require_sites_in_the_module": 0,
                       "entries_for_raises_and_excepts": len(RAISES) + len(EXCEPTS), "m7_test_audit_progress_functions": 28,
                       "m7_node_ids": len(M7_TESTS), "other_family_node_ids": len(other_family),
                       "fully_mirrored_node_ids": len(M7_TESTS) - len(other_family)}}


GROUPS = (("g1_policy", g1_policy), ("g2_windows", g2_windows), ("g3_yield", g3_yield), ("g4_evidence", g4_evidence),
          ("g5_epochs", g5_epochs), ("g6_candidates", g6_candidates), ("g7_degraded_status", g7_degraded_status),
          ("g8_owner_rows", g8_owner_rows))


def run(api) -> dict:
    ws = R.Workspace()
    try:
        result, counts_ = {}, {}
        for name, group in GROUPS:
            result[name] = ws.scrub(group(api, ws))
            counts_[name] = len(result[name])
        result["cases_per_group"] = counts_
        result["coverage"] = coverage(result)
        return result
    finally:
        ws.close()

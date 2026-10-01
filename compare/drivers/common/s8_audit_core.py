"""Shared S8 scenario steps (`research.audit_core`): M7 `application/research.py` (`ResearchAudits`: `seed_backlog`,
`import_audit`, `partition`, `_anchors`, `_claimed_evidence`, `checkpoint`, `_coverage`, `_observed`, `observe_assets`,
`coverage`, `propose`, `execute`, `_queue_review`, `review`, `_eligible`), characterized BEFORE the audit core moves
(DESIGN-s8 §2 row `research.audits`, its CORE module, and §6 V11 step 4). The golden is placement-neutral: it observes
SOURCE behaviour only; the move is the NEXT pilot.

- **b1_backlog_import**: `seed_backlog` (the packaged resource over empty artifacts; M7 `test_backlog_idempotent_and_
  preserves_legacy`; the manifest and history refusals) and `import_audit` (M7 `test_git_inventory_preserves_raw_paths_
  binary_and_symlink`, the idempotent replay and the conflict refusal).
- **b2_partition**: `partition` (the limit, the replay, the anchors), `_anchors` and `_claimed_evidence`.
- **b3_checkpoint**: `checkpoint` (M7 `test_research_audits.py` and `test_audit_checkpoint_outcomes.py`): resume and a stale
  writer, scope and coverage, the forged receipt, the strict wire contract, unresolved subsystems, retained evidence, the
  continuation authorization and its `outbox` row, the typed candidate rejections, execution integrity, rollback.
- **b4_observed_coverage**: `observe_assets`, `_observed`, `_coverage`, `coverage` (the separate completeness ledger).
- **b5_propose_execute**: `propose`, `execute` and `_queue_review`.
- **b6_review**: `review` and `_eligible`, with `ExecutionRecovery.validate_decision` run as SOURCE runs it (its decision is
  recorded in every review case).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later
a target) driver builds. LABELLED doubles (nothing here is an actual Codex, Git, Docker or production verification):
- `Verifier`: the `SourceVerifier` port (M7 `adapters.source_verification.GitSourceVerifier`, a later layer-0 family that never
  runs here): the same result shape and the same manifest checks over the run's artifacts, without Git;
- `Runner`: M7 `FixtureRunner` (`tests/test_research_audits.py`): injected receipts, never an isolated execution;
- the artifacts are M7's OWN `adapters.artifacts.FileArtifacts` over a run-scoped directory (its target counterpart is
  `storage.adapters.file_artifacts.FileArtifacts`);
- `activate`: the rows `Releases.promote` writes that `audit_gate.binding` and `require_adoption` read (the release, the
  deployment pointer, the research control rows): the releases family (`activate_fixture` in M7) is another module.
Where a state has no honest call path (a planted audit, partition or decision row, a store fault) the case is LABELLED where it
is made. Paths are relative to the run directory or reported by type only; the store digests of the buckets each operation
writes are recorded before and after every refusal and every write.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import s8_research_program as R

REPO = "https://github.com/fixture/repo"
COMMIT = "1" * 40
TREE = "2" * 40
OTHER_REPO = "https://github.com/other/repo"
LEASE_UNTIL = "2031-01-01T00:00:00+00:00"
INVENTED = "sha256:" + "c" * 64
DISPLAY_NAME = "docs/zeus/operations/self-improvement-reference-001/SPEC.md"
WATCHED = ("research_audits", "research_backlog", "research_partitions", "research_paths", "research_subsystems",
           "research_checkpoints", "research_evidence_history", "research_receipts", "research_observed_assets",
           "research_adaptations", "research_reviews", "research_approvals", "decisions_pending", "outbox",
           "knowledge_nodes", "knowledge_edges")
RAW_BINARY = b"space\tand\nnewline"


class StoreFault(RuntimeError):
    """LABELLED. An injected store write failure (M7 injects `psycopg.OperationalError`): no real outage happened."""


def canonical_digest(value) -> str:
    return R.canonical_digest(value)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


LINK, NORMAL, BINARY = b64(b"link"), b64(b"normal"), b64(RAW_BINARY)


# ---- labelled doubles ------------------------------------------------------------------------------------------------------
class Verifier:
    """LABELLED. The `SourceVerifier` port (M7 `GitSourceVerifier.verify`): the same result shape (`version`, `repository`,
    `commit`, `tree`, `entries`) and the same checks against the stored manifest, without Git. `drift` is the labelled seam of
    a changed source inventory; `calls` counts the verifications."""

    def __init__(self, api, artifacts):
        self.api, self.artifacts, self.calls, self.drift = api, artifacts, 0, False

    def verify(self, source, entries):
        self.calls += 1
        source.validate()
        for entry in entries:
            entry.validate()
        if len({e.path for e in entries}) != len(entries):
            raise self.api.ContractError("Duplicate inventory path")
        expected = {"version": 1, "repository": source.repository, "commit": source.commit, "tree": source.tree,
                    "entries": [asdict(e) for e in entries]}
        if self.artifacts.document(source.manifest_ref) != expected:
            raise self.api.ContractError("Manifest/source mismatch")
        if self.drift:
            raise self.api.ContractError("Incomplete or changed source inventory")
        for entry in entries:
            if entry.artifact_ref:
                self.artifacts.document(entry.artifact_ref)
        return expected


class Runner:
    """LABELLED. M7 `FixtureRunner`: injected receipts (not an actual isolated or Codex verification). `blocked`/`passed`/
    `outcome` as in M7; `isolation` names the receipt's isolation (the real inert reader's is
    `inert-objects-no-code-execution`); `children` makes the output a JSON document declaring those artifact references;
    `mutate` (labelled seam) replaces the receipt the runner reports; `hook` runs inside `execute_assigned` before the
    receipt exists (the lease can change while the runner works)."""

    def __init__(self, api, artifacts, blocked=False, passed=None, outcome=None, isolation="fixture-isolation",
                 children=None, mutate=None, hook=None):
        self.api, self.artifacts, self.blocked, self.isolation = api, artifacts, blocked, isolation
        self.passed = (not blocked) if passed is None else passed
        self.outcome = outcome or ("isolation_unavailable" if blocked else "executed")
        self.children, self.mutate, self.hook, self.calls = children, mutate, hook, []

    def execute(self, source, command):
        body = ("fixture inspection output" if not self.children else
                self.api.canonical({"stdout": "fixture inspection output", "artifact_refs": list(self.children)}))
        output = self.artifacts.put(body, "test-fixture")["ref"]
        return self.api.ExecutionReceipt(source, "fixture-env", command, self.isolation, 125 if self.blocked else 0, output,
                                         "fixture-runner", self.blocked, passed=self.passed, outcome=self.outcome)

    def execute_assigned(self, source, command, task, workflow):
        self.calls.append(list(command))
        if self.hook is not None:
            self.hook(task, workflow)
        receipt = self.execute(source, command)
        return self.mutate(receipt) if self.mutate is not None else receipt


# ---- the fixture audit ------------------------------------------------------------------------------------------------------
def fixture_source(api, artifacts, commit=COMMIT, tree=TREE):
    """M7 `audit` fixture: the three-entry inventory (a symlink, a text file, a binary blob with a raw path) whose manifest and
    blob envelopes are artifacts of the run; the object ids are the real Git blob ids of the bodies."""
    entries = []
    for raw, mode, body in ((b"link", "120000", b"normal"), (b"normal", "100644", b"source"),
                            (RAW_BINARY, "100644", b"\xff\x00\xfe")):
        oid = hashlib.sha1(b"blob %d\0" % len(body) + body).hexdigest()
        envelope = api.canonical({"version": 1, "encoding": "base64", "bytes_sha256": hashlib.sha256(body).hexdigest(),
                                  "data": b64(body)})
        ref = artifacts.put(envelope, REPO + "@" + commit + ":" + oid)["ref"]
        entries.append(api.InventoryEntry(b64(raw), mode, oid, len(body), ref))
    manifest = {"version": 1, "repository": REPO, "commit": commit, "tree": tree, "entries": [asdict(e) for e in entries]}
    ref = artifacts.put(api.canonical(manifest), "fixture")["ref"]
    return api.SourceIdentity(REPO, commit, tree, ref), entries


def build(api, ws, name, imported=True, runner=True, subsystems=("core",)):
    """M7 `audit` fixture: a `MemoryStore`, the real `Workflow` over the packaged organization, M7's own `FileArtifacts` over
    a run-scoped directory, the labelled verifier and runner, and (by default) the imported audit."""
    store = api.MemoryStore()
    workflow = api.Workflow(store, api.organization())
    artifacts = api.FileArtifacts(str(ws.case(name) / "artifacts"))
    verifier = Verifier(api, artifacts)
    fixture = Runner(api, artifacts) if runner else None
    service = api.ResearchAudits(store, verifier, artifacts, workflow, fixture)
    env = SimpleNamespace(api=api, ws=ws, name=name, store=store, workflow=workflow, artifacts=artifacts, verifier=verifier,
                          runner=fixture, service=service, record=None)
    env.source, env.entries = fixture_source(api, artifacts)
    if imported:
        env.record = service.import_audit(env.source, env.entries, list(subsystems))
    return env


# ---- observations ------------------------------------------------------------------------------------------------------
def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def snap(store) -> dict:
    """`bucket -> "<rows>:<digest16>"` of the watched buckets, and the digest of the whole store."""
    with store.transaction() as tx:
        rows = tx.records()
    out = {}
    for bucket in WATCHED:
        mine = sorted([r["id"], canonical_digest(r["body"])] for r in rows if r["bucket"] == bucket)
        out[bucket] = "%d:%s" % (len(mine), canonical_digest(mine)[:16])
    out["all"] = canonical_digest(sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows))[:16]
    return out


def outcome(api, fn, *args, view=None, **kwargs):
    """The characterized outcome of one call: a digest of its value (and a view of the facts), or the refusal (type, whether it
    is the typed candidate rejection, its text and its cause; an OS error is reported by type only, its text names a path)."""
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:   # the refusal is the characterized result
        out = {"refused": type(exc).__name__, "typed_rejection": isinstance(exc, api.AuditDraftRejected)}
        if not isinstance(exc, OSError):
            out["message"] = str(exc)[:240]
        if exc.__cause__ is not None:
            out["cause"] = type(exc.__cause__).__name__
        return out
    out = {"value": canonical_digest(value)}
    if view is not None:
        out["view"] = view(value)
    return out


def step(env, fn, *args, view=None, **kwargs):
    """One operation with the watched-bucket digests before and after (a refusal changes none of them unless it says so) and
    one tick of the fake clock."""
    before = snap(env.store)
    out = outcome(env.api, fn, *args, view=view, **kwargs)
    after = snap(env.store)
    env.api.advance(0.001)
    return {**out, "before": before, "after": after, "changed": [k for k in before if before[k] != after[k]]}


def record_view(record):
    return {"id": record["id"], "status": record["status"], "activation": record["activation"],
            "subsystems": record["subsystems"], "inventory": len(record["inventory"]), "version": record["version"]}


def partition_view(p):
    return {"audit_id_matches": bool(p["audit_id"]), "generation": p["generation"],
            "paths": len(p["paths"]), "subsystems": p["subsystems"], "remaining_paths": len(p["remaining_paths"]),
            "remaining_subsystems": p["remaining_subsystems"], "open_questions": p["open_questions"], "cursor": p["cursor"]}


def partitions_view(rows):
    return [partition_view(p) for p in rows]


def saved_view(body):
    return {"generation": body["generation"], "cursor": body["cursor"], "evidence_refs": body["evidence_refs"],
            "remaining_paths": len(body["remaining_paths"]), "remaining_subsystems": body["remaining_subsystems"],
            "open_questions": body["open_questions"], "paths": len(body["paths"]), "subsystems": body["subsystems"]}


def receipt_view(body):
    r = body["receipt"]
    return {"audit_id_set": bool(body["audit_id"]), "generation": body["generation"],
            "command": r["command"], "isolation": r["isolation"], "exit_status": r["exit_status"], "passed": r["passed"],
            "outcome": r["outcome"], "inspection_blocked": r["inspection_blocked"], "output_ref": r["output_ref"]}


def coverage_view(c):
    return {"reviewed_paths": c["reviewed_paths"], "remaining_paths": len(c["remaining_paths"]),
            "remaining_subsystems": c["remaining_subsystems"], "observed_assets": c["observed_assets"],
            "open_questions": c["open_questions"], "whole_analysis_complete": c["whole_analysis_complete"],
            "adoption_eligible": c["adoption_eligible"], "reason": c["reason"]}


def coverage_of(env):
    return coverage_view(env.service.coverage(env.record["id"]))


def review_view(r):
    return {"status": r["status"], "sequence": r["sequence"], "accepted": r["review"]["accepted"], "actor": r["review"]["actor"],
            "binding_matches_review": bool(r["review"]["binding"]), "audit_id_set": bool(r["audit_id"])}


def decision_view(row):
    return {"actor": row["actor"], "phase": row["phase"], "status": row["status"], "attempt": row["attempt"],
            "input_keys": sorted(row["input"]), "binding": row["input"]["binding"], "id": row["id"],
            "message": [row["message"]["type"], row["message"]["who"], row["message"]["what"]["action"],
                        row["message"]["correlation_id"]]}


def counts(store, buckets=WATCHED):
    with store.transaction() as tx:
        return {b: len(tx.scan(b)) for b in buckets if tx.scan(b)}


# ---- task, release and lifecycle fixtures ------------------------------------------------------------------------------------
def assign(env, details, action="audit_partition", name="fixture", agent="worker:github"):
    """A real submitted and claimed task (M7 `assigned_partition`)."""
    message = env.api.envelope("task.assign", "lead:research", agent, action, details, name)
    env.workflow.submit(message)
    return env.workflow.claim(agent, "fixture")


def assigned(env, kind="paths", limit=1, name="fixture", generation=False, path=None):
    """One real assigned `audit_partition` task over a real partition of the audit (M7 `assigned_partition`/`claim_partition`)."""
    partitions = env.service.partition(env.record["id"], limit)
    if kind == "paths":
        part = next(p for p in partitions if p["paths"] == [path or NORMAL]) if limit == 1 else next(p for p in partitions if p["paths"])
    else:
        part = next(p for p in partitions if p["subsystems"])
    details = {"audit_id": env.record["id"], "partition_id": part["partition_id"]}
    if generation:
        details["generation"] = part["generation"]
    return part, assign(env, details, name=name)


def activate(env, status="active"):
    """LABELLED. What `Releases.promote` of an audit-enabled candidate writes and `binding`/`require_adoption` read."""
    put(env.store, "releases", "rel-1", {"id": "rel-1", "status": "active", "policy_hash": "policy-hash-1",
                                          "candidate": {"revision": "audit", "audit_lifecycle_version": 1}})
    put(env.store, "deployment", "active", {"release_id": "rel-1", "revision": "audit", "previous": None})
    put(env.store, "research_control", "graph", {"revision": "audit", "tree": "fixture-tree", "organization": "org-1"})
    put(env.store, "research_control", "activation", {"status": status, "release_id": "rel-1", "revision": "audit"})


def evidence(env, text="one traced path"):
    return env.artifacts.put(text, "fixture")["ref"]


def path_disposition(env, path, kind, ref, **overrides):
    """A `PathDisposition` (M7: `PathDisposition(path, 'semantic', [ref], ['symbol'], 'traced', [], '', [])`)."""
    values = {"path": path, "disposition": kind, "evidence_refs": [ref] if ref else [], "symbols": ["symbol"],
              "justification": "traced", "links": [], "method": "", "receipt_ids": []}
    values.update(overrides)
    return env.api.PathDisposition(**values)


def analysis(env, ref, **overrides):
    """A justified-unexecuted subsystem trace (M7 `SubsystemAnalysis('core', ..., tests_not_run=[...])`)."""
    values = {"name": "core", "paths": [env.record["inventory"][0]["path"]], "contracts": ["contract"], "entry_points": ["main"],
              "implementations": ["impl"], "callers": ["caller"], "configuration": ["config"], "storage_authority": ["git"],
              "failure_paths": ["failure"], "tests": [], "receipt_ids": [], "evidence_refs": [ref], "contradictions": [],
              "unresolved_dependencies": [],
              "tests_not_run": [{"test": "upstream suite", "reason": "isolation unavailable", "follow_up": "run in a verified runner"}]}
    values.update(overrides)
    return env.api.SubsystemAnalysis(**values)


def proposal(env, **overrides):
    values = {"source": env.source, "scope": [e["path"] for e in env.record["inventory"]], "source_symbols": ["source:symbol"],
              "behavior": "behavior", "failure_modes": "failures", "harness_symbols": ["harness:symbol"], "overlap": "overlap",
              "boundaries": "boundaries", "ssot": "git/postgres", "six_w": "six-w.v1", "graph_impact": "graph",
              "attribution": "attribution", "license_constraints": "license", "dependency_constraints": "dependencies",
              "decision": "adapt", "reason": "reason", "author": "worker:github"}
    values.update(overrides)
    return env.api.AdaptationProposal(**values)


def complete_audit(env):
    """M7 `complete_fixture_audit`: every partition checkpointed whole under a successful runner receipt."""
    api = env.api
    for part in env.service.partition(env.record["id"], 1):
        task = assign(env, {"audit_id": env.record["id"], "partition_id": part["partition_id"]})
        receipt = env.service.execute(task, env.record["id"], ["fixture-inspection"])
        ref = receipt["receipt"]["output_ref"]
        paths = [api.PathDisposition(p, "binary" if base64.b64decode(p).startswith(b"space") else "semantic", [ref], ["symbol"],
                                     "fixture trace", [], "fixture-inspection", [receipt["id"]]) for p in part["paths"]]
        systems = [api.SubsystemAnalysis(name, [e["path"] for e in env.record["inventory"]], ["contract"], ["main"], ["impl"],
                                         ["caller"], ["config"], ["git"], ["failure"], [json.dumps(["fixture-inspection"])],
                                         [receipt["id"]], [ref], [], [], []) for name in part["subsystems"]]
        saved = env.service.checkpoint(task, replace(api.PartitionCheckpoint(**part), remaining_paths=[],
                                                    remaining_subsystems=[], cursor="done"), paths, systems)
        env.workflow.complete(task, saved)
    return proposal(env)


def lease_review(env, actor):
    """M7 `lease_review`: the pending decision of `actor` leased to the fixture owner."""
    with env.store.transaction() as tx:
        row = next(r for r in tx.scan("decisions_pending") if r["actor"] == actor and r["status"] == "pending")
        row.update(status="running", generation=1, lease_owner="fixture", owner="fixture", lease_until=LEASE_UNTIL)
        tx.put("decisions_pending", row["id"], row)
        return {**row, "_bucket": "decisions_pending"}


def independent_review(env, task, actor, accepted=True, execution=None, **overrides):
    """A review of the leased decision under a fresh runner receipt (M7 `approve_fixture` without the final call)."""
    if execution is None:
        execution = env.service.execute(task, task["input"]["audit_id"], ["fixture-independent-inspection"])["id"]
    values = {"binding": task["input"]["binding"], "actor": actor, "execution_id": execution, "accepted": accepted,
              "license_assessment": "license", "dependency_assessment": "deps", "sre_assessment": "sre",
              "architecture_assessment": "architecture", "graph_assessment": "graph"}
    values.update(overrides)
    return env.api.IndependentReview(**values)


def approve(env, actor):
    """M7 `approve_fixture`: lease, execute, review (the review itself unobserved: it is setup)."""
    task = lease_review(env, actor)
    review = independent_review(env, task, actor)
    env.service.review(task, review)
    return task, review


def lifecycle(env, decision="adapt", approvals=True, hook=None):
    """An activated, completed and proposed audit, optionally approved by both reviewers. Returns the proposal and the tasks.
    `hook` runs after the audit is complete and before the proposal: a task claimed here, while the leased review decisions do not
    yet occupy the executions (M7 claims its partition task at this point too)."""
    activate(env)
    adopted = complete_audit(env)
    adopted = replace(adopted, decision=decision)
    if hook is not None:
        hook()
    env.service.propose(env.record["id"], adopted)
    tasks = {}
    if approvals:
        for actor in ("lead:research", "conductor"):
            tasks[actor] = approve(env, actor)
    return adopted, tasks


def reviewed(env, task, review):
    """One review with the recovery decision `ExecutionRecovery.validate_decision` makes for the leased row, as SOURCE runs it
    (`review` calls it on the owned row first); both are part of the case."""
    def decide():
        with env.store.transaction() as tx:
            env.api.ExecutionRecovery(env.store, env.workflow.org, env.artifacts).validate_decision(
                tx, tx.get("decisions_pending", task["id"]))
        return "accepted"
    return {"validate_decision": outcome(env.api, decide), "review": step(env, env.service.review, task, review, view=review_view)}


# ---- b1: backlog and import --------------------------------------------------------------------------------------------------
def seed_fixture(env, count=5):
    """M7 `test_backlog_idempotent_and_preserves_legacy`: `count` seeds whose manifests are artifacts of the run."""
    seeds = []
    for i in range(count):
        body = {"repository": "https://github.com/fixture/repo%d" % i, "revision": "a" * 40, "files": [{"path": "a"}, {"path": "binary"}]}
        ref = env.artifacts.put(json.dumps(body), "fixture")["ref"]
        seeds.append({"repository": body["repository"], "revision": body["revision"], "files": 2, "manifest_ref": ref})
    return seeds


def plant_history(env, seeds):
    """LABELLED. The historical `reference_audits` rows the backlog is seeded over (M7 plants them the same way)."""
    with env.store.transaction() as tx:
        tx.put("reference_audits", "legacy", {"status": "inventoried_not_reviewed"})
        for i, seed in enumerate(seeds):
            tx.put("reference_audits", str(i), seed)


def seeded(env, seeds):
    with env.api.seeds_from(seeds):
        return env.service.seed_backlog()


def backlog_view(rows):
    return {"n": len(rows), "priorities": [r["priority"] for r in rows], "status": sorted({r["status"] for r in rows}),
            "reviewed_paths": sorted({r["reviewed_paths"] for r in rows}), "remaining_paths": [len(r["remaining_paths"]) for r in rows],
            "source_verified": sorted({r["source_verified"] for r in rows}),
            "historical_reference_ids": [len(r["historical_reference_ids"]) for r in rows],
            "activation": sorted({r["activation"] for r in rows}), "ids_are_seed_digests": [r["id"] for r in rows]}


def b1_backlog_import(api, ws):
    out = {}
    env = build(api, ws, "import", imported=False)
    first = step(env, env.service.import_audit, env.source, env.entries, ["core"], view=record_view)
    out["import_fresh"] = {**first, "verifier_calls": env.verifier.calls}
    again = step(env, env.service.import_audit, env.source, env.entries, ["core"], view=record_view)
    out["import_replay_identical"] = {**again, "same_value": again["value"] == first["value"], "verifier_calls": env.verifier.calls}
    out["import_conflicting_record"] = {**step(env, env.service.import_audit, env.source, env.entries, ["core", "extra"]),
                                        "verifier_calls": env.verifier.calls}
    stored = get(env.store, "research_audits", api.digest(asdict(env.source)))
    out["import_stored_record"] = {"keys": sorted(stored), "inventory_paths": [e["path"] for e in stored["inventory"]],
                                   "status": stored["status"], "source_is_the_identity": stored["source"] == asdict(env.source)}
    other_source, other_entries = fixture_source(api, env.artifacts, commit="3" * 40, tree="4" * 40)
    out["import_sorts_subsystems"] = step(env, env.service.import_audit, other_source, other_entries, ["b", "a"],
                                          view=lambda r: {**record_view(r), "stored_order": r["subsystems"]})
    calls = env.verifier.calls
    for name, subsystems in (("empty", []), ("duplicate", ["core", "core"]), ("blank", ["core", ""])):
        out["import_subsystems_" + name] = {**step(env, env.service.import_audit, env.source, env.entries, subsystems),
                                            "verifier_called": env.verifier.calls != calls}
    bad = replace(env.entries[0], mode="100000")
    out["import_invalid_entry_is_parsed_before_the_verifier"] = {
        **step(env, env.service.import_audit, other_source, [bad, *other_entries[1:]], ["core"]), "verifier_calls": env.verifier.calls}
    noncanonical = replace(other_source, repository=REPO + ".git")
    out["import_invalid_source_is_parsed_before_the_verifier"] = {
        **step(env, env.service.import_audit, noncanonical, other_entries, ["core"]), "verifier_calls": env.verifier.calls}
    out["import_a_non_dataclass_source"] = step(env, env.service.import_audit, "not-a-source", other_entries, ["core"])
    third_source, third_entries = fixture_source(api, env.artifacts, commit="5" * 40, tree="6" * 40)
    env.verifier.drift = True
    out["import_verifier_refusal_writes_nothing"] = step(env, env.service.import_audit, third_source, third_entries, ["core"])
    env.verifier.drift = False
    out["import_omitted_entry_is_a_manifest_mismatch"] = step(env, env.service.import_audit, third_source, third_entries[:-1], ["core"])
    env.service.verifier = None
    out["import_without_a_verifier"] = step(env, env.service.import_audit, third_source, third_entries, ["core"])

    # seed_backlog: the packaged resource over a run whose artifacts never held its manifests
    env = build(api, ws, "seed-packaged", imported=False)
    out["seed_packaged_backlog_over_empty_artifacts"] = step(env, env.service.seed_backlog)

    env = build(api, ws, "seed", imported=False)
    seeds = seed_fixture(env)
    plant_history(env, seeds)
    one = step(env, seeded, env, seeds, view=backlog_view)
    two = step(env, seeded, env, seeds, view=backlog_view)
    out["seed_backlog_first"] = one
    out["seed_backlog_replay_is_identical"] = {**two, "same_value": one["value"] == two["value"]}
    out["seed_backlog_preserves_legacy"] = {"legacy": get(env.store, "reference_audits", "legacy"),
                                            "reference_audits": len(scan(env.store, "reference_audits")),
                                            "outbox": len(scan(env.store, "outbox")), "backlog_rows": len(scan(env.store, "research_backlog"))}
    # An existing backlog row is kept verbatim: the old row, not the new record, is what comes back.
    row = scan(env.store, "research_backlog")[0]
    put(env.store, "research_backlog", row["id"], {**row, "status": "reviewed_elsewhere"})
    kept = step(env, seeded, env, seeds, view=lambda rows: sorted({r["status"] for r in rows}))
    out["seed_backlog_keeps_an_existing_row"] = kept

    env = build(api, ws, "seed-mismatch", imported=False)
    base = {"repository": "https://github.com/fixture/repo0", "revision": "a" * 40, "files": [{"path": "a"}, {"path": "b"}]}
    variants = {"repository": {**base, "repository": "https://github.com/fixture/elsewhere"},
                "revision": {**base, "revision": "b" * 40}, "duplicate_path": {**base, "files": [{"path": "a"}, {"path": "a"}]}}
    for name, body in variants.items():
        ref = env.artifacts.put(json.dumps(body), "fixture")["ref"]
        out["seed_manifest_mismatch_" + name] = step(env, seeded, env, [{"repository": base["repository"], "revision": base["revision"],
                                                                         "files": 2, "manifest_ref": ref}])
    ref = env.artifacts.put(json.dumps(base), "fixture")["ref"]
    out["seed_manifest_mismatch_file_count"] = step(env, seeded, env, [{"repository": base["repository"], "revision": base["revision"],
                                                                        "files": 3, "manifest_ref": ref}])
    good = {"repository": base["repository"], "revision": base["revision"], "files": 2, "manifest_ref": ref}
    out["seed_without_a_historical_audit"] = step(env, seeded, env, [good])
    put(env.store, "reference_audits", "partial", {"repository": base["repository"], "revision": base["revision"]})
    out["seed_with_a_history_row_lacking_the_manifest"] = step(env, seeded, env, [good])
    put(env.store, "reference_audits", "full", good)
    out["seed_with_a_matching_history_row"] = step(env, seeded, env, [good], view=backlog_view)
    return out


# ---- b2: partition, anchors, claimed evidence --------------------------------------------------------------------------------
def b2_partition(api, ws):
    out = {}
    env = build(api, ws, "partition")
    audit_id = env.record["id"]
    first = step(env, env.service.partition, audit_id, 1, view=partitions_view)
    out["limit_one_splits_every_scope_item"] = first
    out["partition_ids_are_digests_of_audit_kind_scope"] = {
        "sorted": [p["partition_id"] for p in scan(env.store, "research_partitions")] == sorted(
            p["partition_id"] for p in scan(env.store, "research_partitions")),
        "ids": sorted(p["partition_id"] for p in scan(env.store, "research_partitions"))}
    replay = step(env, env.service.partition, audit_id, 2, view=partitions_view)
    out["replay_ignores_a_new_limit"] = {**replay, "same_value": replay["value"] == first["value"]}
    out["replay_is_sorted_by_partition_id"] = {"ids": [p["partition_id"] for p in env.service.partition(audit_id, 1)]}

    env = build(api, ws, "partition-default")
    out["default_limit_keeps_each_scope_whole"] = step(env, env.service.partition, env.record["id"], view=partitions_view)
    env = build(api, ws, "partition-two")
    out["limit_two_pages_the_paths"] = step(env, env.service.partition, env.record["id"], 2, view=partitions_view)
    env = build(api, ws, "partition-max")
    out["limit_128_is_the_largest_budget"] = step(env, env.service.partition, env.record["id"], 128, view=partitions_view)
    env = build(api, ws, "partition-subsystems", subsystems=("a", "b", "c"))
    out["subsystems_survive_task_budgets"] = step(env, env.service.partition, env.record["id"], 2, view=partitions_view)

    env = build(api, ws, "partition-invalid")
    for name, limit in (("zero", 0), ("negative", -1), ("over_128", 129), ("bool", True), ("string", "1"), ("float", 1.0), ("none", None)):
        out["invalid_budget_" + name] = step(env, env.service.partition, env.record["id"], limit)
    out["unknown_audit"] = step(env, env.service.partition, "no-such-audit")

    # `_anchors` (M7 `research.py` L108-128): the authoritative references of THIS audit, from trusted records only.
    env = build(api, ws, "anchors")
    part, task = assigned(env, "paths")
    receipt = env.service.execute(task, env.record["id"], ["fixture-inspection"])
    ref = evidence(env)
    foreign = "sha256:" + "d" * 64
    env.service.checkpoint(task, replace(api.PartitionCheckpoint(**part), evidence_refs=[ref], remaining_paths=[], cursor="next"),
                           [path_disposition(env, part["paths"][0], "semantic", ref)], [])
    with env.store.transaction() as tx:
        tx.put("research_partitions", "foreign-partition", {"audit_id": "other", "evidence_refs": [foreign]})
        tx.put("research_checkpoints", "foreign-checkpoint", {"audit_id": "other", "evidence_refs": [foreign]})
        tx.put("research_receipts", "foreign-receipt", {"audit_id": "other", "receipt": {"output_ref": foreign}})
        audit = tx.get("research_audits", env.record["id"])
        refs = env.service._anchors(tx, audit)
    entry_refs = {e["artifact_ref"] for e in env.record["inventory"]}
    out["anchors_of_this_audit"] = {
        "count": len(refs), "manifest": env.source.manifest_ref in refs, "inventory_artifacts": entry_refs <= refs,
        "checkpoint_evidence": ref in refs, "receipt_output": receipt["receipt"]["output_ref"] in refs, "foreign": foreign in refs,
        "exactly": refs == entry_refs | {env.source.manifest_ref, ref, receipt["receipt"]["output_ref"]}}
    for name, source in (("without_manifest_ref", {"repository": REPO}), ("empty_source", {}), ("no_source", None)):
        def anchors(source=source):
            with env.store.transaction() as tx:
                return env.service._anchors(tx, {**audit, "source": source})
        out["anchors_" + name] = outcome(api, anchors)
    plain = {**audit, "inventory": [{**audit["inventory"][0], "artifact_ref": None}]}   # LABELLED: a gitlink entry has no artifact
    with env.store.transaction() as tx:
        out["anchors_skip_entries_without_an_artifact"] = {"refs": len(env.service._anchors(tx, plain)),
                                                           "none_in": None in env.service._anchors(tx, plain)}

    # `_claimed_evidence` (L130-146): only an ABSENT unanchored body is the candidate's own fault.
    env = build(api, ws, "claimed")
    anchored = evidence(env, "anchored evidence")
    unanchored = evidence(env, "unanchored evidence")
    modified = evidence(env, "will be modified")
    nometa = evidence(env, "will lose its metadata")
    gone = evidence(env, "will be removed")
    root = env.artifacts.root
    (root / (modified[7:] + ".txt")).write_text("rewritten", encoding="utf-8")
    (root / (nometa[7:] + ".json")).unlink()
    (root / (gone[7:] + ".txt")).unlink()
    anchors = {anchored, gone}
    check = env.service._claimed_evidence
    out["claimed_anchored_and_unanchored_present"] = step(env, check, anchors, [anchored, unanchored])
    out["claimed_no_references"] = step(env, check, anchors, [])
    out["claimed_unanchored_absent_is_the_one_typed_raise"] = step(env, check, anchors, [INVENTED])
    out["claimed_anchored_absent_stays_a_hard_failure"] = step(env, check, anchors, [gone])
    out["claimed_unanchored_modified_stays_a_hard_failure"] = step(env, check, anchors, [modified])
    out["claimed_unanchored_metadata_missing_stays_a_hard_failure"] = step(env, check, anchors, [nometa])
    out["claimed_unanchored_malformed_reference"] = step(env, check, anchors, ["not-a-reference"])
    out["claimed_stops_at_the_first_refusal"] = step(env, check, anchors, [unanchored, INVENTED, modified])
    return out



# ---- b3: checkpoint ----------------------------------------------------------------------------------------------------------
def cp(env, part, **overrides):
    """M7 `replace(PartitionCheckpoint(**part), ...)`."""
    return replace(env.api.PartitionCheckpoint(**part), **overrides)


def checkpointed(env, task, checkpoint, dispositions=(), analyses=(), continuation=None, view=saved_view):
    return step(env, env.service.checkpoint, task, checkpoint, list(dispositions), list(analyses), continuation, view=view)


def with_coverage(env, result):
    return {**result, "coverage": coverage_of(env)}


def plant_audit(env, entries, name):
    """LABELLED. A second audit of the SAME verified source with a trusted inventory the importer cannot produce (M7
    `test_a_submodule_classification_claim_is_a_typed_rejection`: the fixture repository has no gitlink): its audit row, one
    partition over every path and one assigned task. No real submodule was acquired or verified here."""
    audit_id = env.api.digest({"fixture": name})
    paths = [e.path for e in entries]
    checkpoint = env.api.PartitionCheckpoint(audit_id, env.api.digest({"fixture": name + "-partition"}), 0, paths, [], [], paths, [], [],
                                             "pending")
    checkpoint.validate()
    with env.store.transaction() as tx:
        tx.put("research_audits", audit_id, {"id": audit_id, "version": 1, "source": asdict(env.source),
                                              "inventory": [asdict(e) for e in entries], "subsystems": [],
                                              "status": "source_verified_not_reviewed"})
        tx.put("research_partitions", checkpoint.partition_id, asdict(checkpoint))
    task = assign(env, {"audit_id": audit_id, "partition_id": checkpoint.partition_id, "generation": 0}, name=name)
    return audit_id, checkpoint, task


def envelope_artifact(env, data_text, label):
    return env.artifacts.put(env.api.canonical({"version": 1, "encoding": "base64", "bytes_sha256": "0" * 64, "data": data_text}),
                             label)["ref"]


def b3_checkpoint(api, ws):
    out = {}
    b3_resume_scope_receipt_wire(api, ws, out)
    b3_unresolved_and_history(api, ws, out)
    b3_continuation(api, ws, out)
    b3_typed_rejections(api, ws, out)
    b3_receipts_and_tests(api, ws, out)
    b3_planted_inventory(api, ws, out)
    b3_integrity_and_rollback(api, ws, out)
    return out


def b3_resume_scope_receipt_wire(api, ws, out):
    # M7 `test_checkpoint_resume_and_stale_writer`
    env = build(api, ws, "resume")
    part, task = assigned(env, "paths")
    ref = evidence(env, "observed implementation and callers")
    disposition = path_disposition(env, part["paths"][0], "semantic", ref, justification="implementation traced")
    checkpoint = cp(env, part, evidence_refs=[ref], remaining_paths=[], cursor="next")
    saved = checkpointed(env, task, checkpoint, [disposition])
    out["resume_saves_generation_one"] = saved
    out["resume_coverage_after_one_path"] = coverage_of(env)
    out["resume_replay_is_a_stale_partition_writer"] = checkpointed(env, task, checkpoint, [disposition])
    row = get(env.store, "tasks", task["id"])
    put(env.store, "tasks", task["id"], {**row, "generation": row["generation"] + 1})
    out["resume_after_the_lease_generation_moved"] = checkpointed(env, task, env.api.PartitionCheckpoint(
        **get(env.store, "research_partitions", part["partition_id"])))
    row = get(env.store, "tasks", task["id"])
    out["resume_stored_rows"] = {"research_paths": len(scan(env.store, "research_paths")),
                                 "research_evidence_history": len(scan(env.store, "research_evidence_history")),
                                 "research_checkpoints": len(scan(env.store, "research_checkpoints")),
                                 "partition_generation": get(env.store, "research_partitions", part["partition_id"])["generation"]}

    # M7 `test_cannot_drop_scope_or_duplicate_coverage`, `test_a_valid_owner_submitting_duplicates_...`
    env = build(api, ws, "scope")
    part, task = assigned(env, "paths", generation=True)
    out["scope_dropping_remaining_work_does_not_reconcile"] = checkpointed(env, task, cp(env, part, remaining_paths=[]))
    out["scope_emptying_the_scope_is_a_scope_change"] = checkpointed(env, task, cp(env, part, paths=[], remaining_paths=[]))
    unreviewed = path_disposition(env, part["paths"][0], "unreviewed", None, justification="", symbols=[])
    out["scope_duplicate_path_records_are_a_typed_rejection"] = checkpointed(env, task, cp(env, part), [unreviewed, unreviewed])
    ref = evidence(env)
    semantic_record = path_disposition(env, part["paths"][0], "semantic", ref)
    duplicate = replace(semantic_record, disposition="unreviewed", evidence_refs=[], justification="")
    out["valid_owner_duplicate_paths"] = checkpointed(env, task, cp(env, part), [semantic_record, duplicate])
    systems = analysis(env, ref)
    out["valid_owner_duplicate_subsystems"] = checkpointed(env, task, cp(env, part), [], [systems, replace(systems)])
    out["valid_owner_lease_untouched_by_the_rejections"] = {
        "completed": env.workflow.complete(task, {"analysis": {"outcome": "analysis_rejected"}})["status"],
        "partition_unchanged": get(env.store, "research_partitions", part["partition_id"]) == part}
    out["scope_rows_after_the_refusals"] = {"research_paths": len(scan(env.store, "research_paths"))}

    # M7 `test_forged_receipt_cannot_advance_checkpoint`
    env = build(api, ws, "forged")
    part, task = assigned(env, "paths")
    ref = evidence(env, "model says command passed")
    forged = path_disposition(env, part["paths"][0], "binary", ref, justification="claimed inspection", method="model",
                              receipt_ids=["forged-runner-receipt"])
    out["forged_receipt_cannot_advance_the_checkpoint"] = with_coverage(
        env, checkpointed(env, task, cp(env, part, remaining_paths=[]), [forged]))

    # M7 `test_strict_wire_contract_rejects_unknown_fields_and_coercion` and the wire boundary `checkpoint`/`import_audit` share
    env = build(api, ws, "wire")
    document = {"version": 1, "kind": "SourceIdentity", "record": asdict(env.source)}
    out["wire_source_identity_round_trips"] = {"equal": api.parse_record(document) == env.source}
    for name, change in (("version_is_a_bool", ("version", True)), ("commit_is_an_int", ("commit", 123)), ("unknown_field", ("extra", "ignored")),
                         ("missing_field", ("tree", None))):
        field, value = change
        record = {**document["record"], field: value}
        if name == "missing_field":
            record.pop("tree")
        out["wire_" + name] = outcome(api, api.parse_record, {**document, "record": record})
    for name, changed in (("envelope_extra_key", {**document, "x": 1}), ("envelope_version_two", {**document, "version": 2}),
                          ("envelope_unknown_kind", {**document, "kind": "Nope"}), ("envelope_not_a_dict", [document]),
                          ("record_not_a_dict", {**document, "record": [1]})):
        out["wire_" + name] = outcome(api, api.parse_record, changed)
    adopted = proposal(env)
    review = env.api.IndependentReview("b" * 64, "lead:research", "e" * 64, True, "license", "deps", "sre", "architecture", "graph")
    for kind, value in (("AdaptationProposal", adopted), ("IndependentReview", review)):
        round_trip = {"equal": api.parse_record({"version": 1, "kind": kind, "record": asdict(value)}) == value}
        for version in (0, 2, True, "1"):
            round_trip["version_%r" % (version,)] = outcome(api, api.parse_record, {"version": 1, "kind": kind, "record": {**asdict(value), "version": version}})
        out["wire_%s_round_trips_and_refuses_other_versions" % kind] = round_trip
    part, task = assigned(env, "paths")
    out["wire_checkpoint_generation_is_a_bool"] = checkpointed(env, task, replace(api.PartitionCheckpoint(**part), generation=True))
    out["wire_checkpoint_paths_is_a_tuple"] = checkpointed(env, task, replace(api.PartitionCheckpoint(**part), paths=tuple(part["paths"])))
    out["wire_checkpoint_scope_item_is_not_a_string"] = checkpointed(env, task, replace(api.PartitionCheckpoint(**part), paths=[1]))
    ref = evidence(env)
    out["wire_record_with_an_unknown_disposition"] = checkpointed(
        env, task, cp(env, part), [path_disposition(env, part["paths"][0], "partial", ref)])
    out["wire_record_that_fails_its_own_validation"] = checkpointed(
        env, task, cp(env, part), [path_disposition(env, part["paths"][0], "semantic", None)])
    out["wire_checkpoint_that_fails_its_own_validation"] = checkpointed(env, task, replace(api.PartitionCheckpoint(**part), cursor=""))
    out["wire_checkpoint_not_a_dataclass"] = checkpointed(env, task, {"audit_id": "x"})

    # trusted anchors (M7 `test_trusted_anchor_failures_stay_ordinary_execution_failures`, the combined-fault matrix)
    for name in ("stale_generation", "changed_scope", "foreign_assignment", "foreign_audit", "stale_ownership"):
        env = build(api, ws, "trusted-" + name)
        part, task = assigned(env, "paths", limit=32 if name == "changed_scope" else 1, generation=True)
        ref = evidence(env)
        disposition = path_disposition(env, part["paths"][0], "semantic", ref)
        checkpoint = cp(env, part)
        if name == "stale_generation":
            checkpoint = replace(checkpoint, generation=part["generation"] + 1)
        elif name == "changed_scope":
            checkpoint = replace(checkpoint, paths=part["paths"][:1], remaining_paths=part["remaining_paths"][:1])
        elif name == "foreign_assignment":
            checkpoint = replace(checkpoint, partition_id=api.digest({"foreign": "partition"}))
        elif name == "foreign_audit":
            checkpoint = replace(checkpoint, audit_id="another-audit")
        else:
            env.workflow.complete(task, {"analysis": {"outcome": "analysis_rejected"}})
        out["trusted_" + name] = with_coverage(env, checkpointed(env, task, checkpoint, [disposition]))
        duplicates = [disposition, replace(disposition, disposition="unreviewed", evidence_refs=[], justification="")]
        out["trusted_" + name + "_with_duplicate_claims_is_still_the_trusted_failure"] = checkpointed(env, task, checkpoint, duplicates)

    env = build(api, ws, "stale-partitions")
    ghost = assign(env, {"audit_id": env.record["id"], "partition_id": "no-such-partition"}, name="ghost-partition")
    ghost_cp = api.PartitionCheckpoint(env.record["id"], "no-such-partition", 0, [NORMAL], [], [], [NORMAL], [], [], "pending")
    out["stale_partition_that_does_not_exist"] = checkpointed(env, ghost, ghost_cp)
    env.workflow.complete(ghost, {"analysis": {"outcome": "analysis_rejected"}})   # one running task per agent
    # LABELLED: a partition row of ANOTHER audit that this audit's task names (no honest call path stores one).
    put(env.store, "research_partitions", "elsewhere", {**asdict(api.PartitionCheckpoint("other-audit", "elsewhere", 0, [NORMAL], [], [],
                                                                                         [NORMAL], [], [], "pending"))})
    other = assign(env, {"audit_id": env.record["id"], "partition_id": "elsewhere"}, name="elsewhere")
    elsewhere_cp = api.PartitionCheckpoint(env.record["id"], "elsewhere", 0, [NORMAL], [], [], [NORMAL], [], [], "pending")
    out["stale_partition_of_another_audit"] = checkpointed(env, other, elsewhere_cp)
    env.workflow.complete(other, {"analysis": {"outcome": "analysis_rejected"}})
    # LABELLED: a partition whose audit row is absent (no honest call path removes an audit).
    put(env.store, "research_partitions", "orphan", asdict(api.PartitionCheckpoint("ghost-audit", "orphan", 0, [NORMAL], [], [], [NORMAL],
                                                                                   [], [], "pending")))
    orphan = assign(env, {"audit_id": "ghost-audit", "partition_id": "orphan"}, name="orphan")
    out["unknown_audit_behind_an_assigned_partition"] = checkpointed(
        env, orphan, api.PartitionCheckpoint("ghost-audit", "orphan", 0, [NORMAL], [], [], [NORMAL], [], [], "pending"))
    env.workflow.complete(orphan, {"analysis": {"outcome": "analysis_rejected"}})
    # LABELLED: an audit row whose source lost its manifest reference (SourceIdentity.validate never lets one be imported).
    with env.store.transaction() as tx:
        audit = tx.get("research_audits", env.record["id"])
        tx.put("research_audits", env.record["id"], {**audit, "source": {"repository": REPO}})
    part = next(p for p in env.service.partition(env.record["id"], 1) if p["paths"] == [NORMAL])
    task = assign(env, {"audit_id": env.record["id"], "partition_id": part["partition_id"]}, name="no-manifest")
    out["audit_source_without_a_manifest_is_a_trusted_failure"] = checkpointed(env, task, cp(env, part))
    out["audit_source_without_a_manifest_but_duplicates_is_a_candidate_rejection"] = checkpointed(
        env, task, cp(env, part), [path_disposition(env, NORMAL, "unreviewed", None, justification="", symbols=[])] * 2)


def b3_unresolved_and_history(api, ws, out):
    # M7 `test_missing_execution_and_unresolved_subsystems_stay_remaining`
    env = build(api, ws, "unresolved-planted")
    ref = evidence(env, "subsystem evidence")
    trace = analysis(env, ref, tests=["test"], receipt_ids=[], tests_not_run=[])
    out["unresolved_missing_execution_cannot_validate"] = outcome(api, trace.validate)
    trace = replace(trace, tests_not_run=[{"test": "test", "reason": "isolation unavailable", "follow_up": "run in verified runner"}])
    out["unresolved_explained_not_run_validates"] = outcome(api, trace.validate)
    put(env.store, "research_subsystems", "fixture", {"audit_id": env.record["id"], "record": asdict(trace)})   # LABELLED row
    out["unresolved_planted_row_stays_remaining"] = coverage_of(env)
    put(env.store, "research_paths", "bad", {"audit_id": env.record["id"], "record": {**asdict(path_disposition(env, NORMAL, "semantic", ref)),
                                                                                      "disposition": "partial"}})
    out["coverage_over_a_corrupt_path_row"] = outcome(api, env.service.coverage, env.record["id"])
    put(env.store, "research_paths", "bad", {"audit_id": "another-audit", "record": {"nonsense": True}})
    put(env.store, "research_subsystems", "fixture", {"audit_id": env.record["id"], "record": {**asdict(trace), "tests_not_run": [{}]}})
    out["coverage_over_a_corrupt_subsystem_row"] = outcome(api, env.service.coverage, env.record["id"])

    for kind in ("tests_not_run", "contradictions", "unresolved_dependencies", "all_resolved"):
        env = build(api, ws, "unresolved-" + kind)
        env.service.runner = Runner(api, env.artifacts)
        part, task = assigned(env, "subsystems", generation=True)
        ref = evidence(env, "subsystem evidence")
        if kind == "all_resolved":
            receipt = env.service.execute(task, env.record["id"], ["pytest", "-q"])["id"]
            trace = analysis(env, ref, tests=[json.dumps(["pytest", "-q"])], receipt_ids=[receipt], tests_not_run=[])
            remaining = []
        else:
            overrides = {"tests_not_run": [{"test": "t", "reason": "r", "follow_up": "f"}]}
            if kind != "tests_not_run":
                overrides = {kind: ["x"]}
                receipt = env.service.execute(task, env.record["id"], ["pytest", "-q"])["id"]
                overrides.update(tests=[json.dumps(["pytest", "-q"])], receipt_ids=[receipt], tests_not_run=[])
            trace = analysis(env, ref, **overrides)
            remaining = ["core"]
        out["subsystem_" + kind] = with_coverage(env, checkpointed(env, task, cp(env, part, remaining_subsystems=remaining), [], [trace]))

    # M7 `test_unexecuted_subsystem_persists_but_cannot_complete_or_adopt[False/True]`
    for with_receipt in (False, True):
        env = build(api, ws, "unexecuted-%s" % with_receipt)
        held = {}

        def claim_subsystem_partition():
            held["part"] = next(p for p in scan(env.store, "research_partitions") if p["subsystems"])
            held["task"] = assign(env, {"audit_id": env.record["id"], "partition_id": held["part"]["partition_id"]}, name="partial-tests")

        adopted, _ = lifecycle(env, hook=claim_subsystem_partition)
        part, task = held["part"], held["task"]
        case = {"eligible_before": coverage_of(env)["adoption_eligible"]}
        ref = evidence(env, "tests could not run")
        receipts = [env.service.execute(task, env.record["id"], ["source-list"])["id"]] if with_receipt else []
        trace = analysis(env, ref, receipt_ids=receipts)
        case["saved"] = checkpointed(env, task, cp(env, part, remaining_subsystems=["core"]), [], [trace])
        saved = get(env.store, "research_partitions", part["partition_id"])
        with env.store.transaction() as tx:
            row = next(r for r in tx.scan("research_subsystems") if r["audit_id"] == env.record["id"])
            case["row_is_the_analysis"] = row["record"] == asdict(trace)
            case["history_holds_the_analysis"] = any(r["record"] == asdict(trace) for r in tx.scan("research_evidence_history"))
        case["coverage"] = coverage_of(env)
        case["reconcile_refused"] = checkpointed(env, task, replace(api.PartitionCheckpoint(**saved), remaining_subsystems=[]), [], [trace])
        case["propose_refused"] = step(env, env.service.propose, env.record["id"], adopted)
        case["without_tests"] = outcome(api, replace(trace, tests_not_run=[]).validate)
        for field in ("test", "reason", "follow_up"):
            case["unexplained_" + field] = outcome(api, replace(trace, tests_not_run=[{**trace.tests_not_run[0], field: ""}]).validate)
        out["unexecuted_subsystem_%s_receipt" % ("with" if with_receipt else "without")] = case

    # M7 `test_checkpoint_history_retains_transitive_evidence`: the module's part (the rows that keep the evidence reachable)
    env = build(api, ws, "history")
    part, task = assigned(env, "paths")
    leaf = evidence(env, "original evidence")
    parent = env.artifacts.put(api.canonical({"original_ref": leaf}), "fixture")["ref"]
    saved = checkpointed(env, task, cp(env, part, remaining_paths=[], cursor="next"), [path_disposition(env, part["paths"][0], "semantic", parent)])
    with env.store.transaction() as tx:
        history = tx.scan("research_checkpoints")
        records = tx.scan("research_evidence_history")
        anchors = env.service._anchors(tx, tx.get("research_audits", env.record["id"]))
    out["history_retains_the_named_evidence"] = {
        "saved": saved, "checkpoint_rows": len(history), "history_rows": len(records),
        "checkpoint_row_is_the_saved_body": history[0] == get(env.store, "research_partitions", part["partition_id"]),
        "parent_is_an_anchor": parent in anchors, "leaf_is_named_only_inside_the_parent": leaf not in anchors,
        "entries_still_inspectable": all(env.artifacts.inspect(e.artifact_ref)["ref"] == e.artifact_ref for e in env.entries)}
    # M7 `test_scheduler_deduplicates_and_resumes_checkpoint_generation`: the module's part (context exhaustion)
    env = build(api, ws, "context-budget")
    activate(env)
    part, task = assigned(env, "paths", generation=True)
    out["context_exhaustion_retains_every_remaining_path"] = checkpointed(env, task, cp(env, part, cursor="context-budget"))
    again = get(env.store, "research_partitions", part["partition_id"])
    out["context_exhaustion_second_checkpoint"] = checkpointed(env, task, env.api.PartitionCheckpoint(**again))
    out["context_exhaustion_coverage"] = coverage_of(env)


def b3_continuation(api, ws, out):
    # the continuation authorization: sender, audit and partition binding, and its `outbox` row (L257-263)
    def continuation_case(name, build_message, evidence_first=False):
        env = build(api, ws, "continuation-" + name)
        part, task = assigned(env, "paths", generation=True)
        message = build_message(env, part)
        result = checkpointed(env, task, cp(env, part), [], [], message)
        rows = scan(env.store, "outbox")
        with env.store.transaction() as tx:
            outbox_keys = {r["id"] for r in tx.records() if r["bucket"] == "outbox"}
        return env, part, task, {**result, "outbox": [{"sent": r["sent"], "type": r["message"]["type"], "who": r["message"]["who"],
                                                       "message_is_the_continuation": r["message"] == message,
                                                       "keyed_by_message_id": r["message"]["message_id"] in outbox_keys} for r in rows],
                                 "partition_generation": get(env.store, "research_partitions", part["partition_id"])["generation"]}

    def report(env, part, **details):
        return env.api.envelope("task.result", "worker:github", "lead:research", "audit_partition",
                                {"audit_id": details.get("audit_id", env.record["id"]),
                                 "partition_id": details.get("partition_id", part["partition_id"])}, "continuation")

    env, part, task, out["continuation_valid_report_is_queued"] = continuation_case("valid", report)
    out["continuation_sender_is_not_the_task_agent"] = continuation_case(
        "sender", lambda env, part: env.api.envelope("task.assign", "lead:research", "worker:github", "audit_partition",
                                                     {"audit_id": env.record["id"], "partition_id": part["partition_id"]}, "c"))[3]
    out["continuation_other_audit"] = continuation_case("audit", lambda env, part: report(env, part, audit_id="another-audit"))[3]
    out["continuation_other_partition"] = continuation_case("partition", lambda env, part: report(env, part, partition_id="another"))[3]
    out["continuation_without_details"] = continuation_case(
        "details", lambda env, part: env.api.envelope("task.result", "worker:github", "lead:research", "audit_partition", {}, "c"))[3]
    out["continuation_not_on_the_reporting_edge"] = continuation_case(
        "edge", lambda env, part: env.api.envelope("task.result", "worker:github", "conductor", "audit_partition",
                                                   {"audit_id": env.record["id"], "partition_id": part["partition_id"]}, "c"))[3]
    out["continuation_unknown_recipient"] = continuation_case(
        "unknown", lambda env, part: env.api.envelope("task.result", "worker:github", "nobody", "audit_partition",
                                                      {"audit_id": env.record["id"], "partition_id": part["partition_id"]}, "c"))[3]
    out["continuation_empty_is_ignored"] = continuation_case("empty", lambda env, part: {})[3]
    out["continuation_none_is_ignored"] = continuation_case("none", lambda env, part: None)[3]
    out["continuation_malformed_message"] = continuation_case("malformed", lambda env, part: {"who": {}})[3]


def b3_typed_rejections(api, ws, out):
    # the candidate-claim matrix of M7 `test_audit_checkpoint_outcomes.py` (each is a typed rejection that commits nothing)
    for case in ("duplicate_records", "foreign_record", "display_name_link", "unknown_link_identity", "invented_evidence",
                 "invented_checkpoint_evidence", "binary_without_receipt", "unsupported_binary_claim", "missing_receipt_claim",
                 "foreign_subsystem", "generated_with_a_known_link", "duplicate_with_a_known_link", "binary_disposition_without_a_receipt_is_a_wire_failure"):
        env = build(api, ws, "claim-" + case)
        activate(env)
        part, task = assigned(env, "paths", limit=32, generation=True)   # M7's default budget: one partition holds every path
        ref = evidence(env, "one traced path")
        trusted = cp(env, part)
        record = path_disposition(env, part["paths"][0], "semantic", ref)
        dispositions, analyses = [record], []
        if case == "duplicate_records":
            dispositions = [record, replace(record, disposition="unreviewed", evidence_refs=[], justification="")]
        elif case == "foreign_record":
            dispositions = [replace(record, path="Zm9yZWlnbg==")]
        elif case == "display_name_link":
            dispositions = [replace(record, disposition="generated", links=[DISPLAY_NAME])]
        elif case == "unknown_link_identity":
            dispositions = [replace(record, disposition="duplicate", links=[b64(b"absent")])]
        elif case == "invented_evidence":
            dispositions = [replace(record, evidence_refs=[INVENTED])]
        elif case == "invented_checkpoint_evidence":
            trusted = replace(trusted, evidence_refs=[INVENTED])
        elif case == "binary_without_receipt":
            dispositions = [replace(record, path=BINARY)]
        elif case == "unsupported_binary_claim":
            dispositions = [replace(record, path=BINARY, disposition="binary", method="eyeballed", receipt_ids=["invented-receipt"])]
        elif case == "missing_receipt_claim":
            dispositions = [replace(record, receipt_ids=["invented-receipt"])]
        elif case == "foreign_subsystem":
            dispositions, analyses = [], [analysis(env, ref, name="other")]
        elif case in ("generated_with_a_known_link", "duplicate_with_a_known_link"):
            dispositions = [replace(record, disposition=case.split("_")[0], links=[NORMAL])]
            trusted = replace(trusted, remaining_paths=[p for p in part["paths"] if p != record.path])
        else:
            dispositions = [replace(record, disposition="binary", method="m", receipt_ids=[])]
        out["claim_" + case] = with_coverage(env, checkpointed(env, task, trusted, dispositions, analyses))

    # trace claims on a subsystem partition (M7 `test_subsystem_trace_claims_are_typed_rejections_that_commit_nothing`)
    env = build(api, ws, "claim-unknown-subsystem-path")
    part, task = assigned(env, "subsystems", generation=True)
    ref = evidence(env, "subsystem evidence")
    out["claim_unknown_subsystem_path"] = with_coverage(env, checkpointed(
        env, task, cp(env, part, remaining_subsystems=[]), [], [analysis(env, ref, paths=[b64(b"never/inventoried")])]))
    # the late reconciliation rejection rolls back rows it already staged (M7 `test_a_late_reconciliation_rejection_...`)
    env = build(api, ws, "late-reconcile")
    activate(env)
    part, task = assigned(env, "subsystems", generation=True)
    ref = evidence(env, "subsystem evidence")
    trace = analysis(env, ref)
    late = checkpointed(env, task, cp(env, part, remaining_subsystems=[]), [], [trace])
    out["late_reconciliation_rejection"] = {**late, "staged_rows_rolled_back": {
        "research_subsystems": len(scan(env.store, "research_subsystems")),
        "research_evidence_history": len(scan(env.store, "research_evidence_history")),
        "research_checkpoints": len(scan(env.store, "research_checkpoints")),
        "partition_kept_generation_and_scope": get(env.store, "research_partitions", part["partition_id"]) == part}}
    out["late_reconciliation_honest_version_checkpoints"] = checkpointed(env, task, cp(env, part), [], [trace])
    # the owned task can still be completed after a rejection rolled back (M7 `test_the_owned_task_can_still_be_completed_...`)
    env = build(api, ws, "retained-completion")
    part, task = assigned(env, "subsystems", generation=True)
    ref = evidence(env, "subsystem evidence")
    refusal = checkpointed(env, task, cp(env, part, remaining_subsystems=[]), [], [analysis(env, ref)])
    out["rejection_leaves_the_task_completable"] = {
        "refusal": refusal["refused"], "completed": env.workflow.complete(task, {"analysis": {"outcome": "analysis_rejected"}})["status"],
        "subsystems": len(scan(env.store, "research_subsystems")),
        "partition_unchanged": get(env.store, "research_partitions", part["partition_id"]) == part}
    # reconciliation of the candidate's own account of the remaining work
    env = build(api, ws, "reconcile")
    part, task = assigned(env, "paths", generation=True)
    ref = evidence(env)
    record = path_disposition(env, part["paths"][0], "semantic", ref)
    out["reconcile_claims_the_dispositioned_path_still_remains"] = checkpointed(env, task, cp(env, part), [record])
    out["reconcile_claims_a_partial_scope_remains"] = checkpointed(env, task, cp(env, part, remaining_paths=[]), [])
    out["reconcile_accepts_an_exact_account"] = with_coverage(env, checkpointed(env, task, cp(env, part, remaining_paths=[]), [record]))
    for kind in ("unreviewed", "unavailable"):
        env = build(api, ws, "reconcile-" + kind)
        part, task = assigned(env, "paths", generation=True)
        record = path_disposition(env, part["paths"][0], kind, None, justification="", symbols=[])
        out["disposition_%s_is_persisted_but_never_coverage" % kind] = with_coverage(env, checkpointed(env, task, cp(env, part), [record]))
        out["disposition_%s_rows" % kind] = {"research_paths": len(scan(env.store, "research_paths")),
                                             "research_evidence_history": len(scan(env.store, "research_evidence_history"))}


def b3_receipts_and_tests(api, ws, out):
    # claimed test commands (L219-233; INV-RESEARCH-003) and M7 `test_inventory_receipt_cannot_clear_claimed_test_coverage[2]`
    def claim(name, commands, tests, not_run=(), isolation="fixture-isolation", remaining=()):
        env = build(api, ws, "test-" + name)
        env.service.runner = Runner(api, env.artifacts, isolation=isolation)
        part, task = assigned(env, "subsystems", generation=True)
        ref = evidence(env, "subsystem evidence")
        receipts = [env.service.execute(task, env.record["id"], c)["id"] for c in commands]
        trace = analysis(env, ref, tests=list(tests), receipt_ids=receipts, tests_not_run=list(not_run))
        out["test_claim_" + name] = with_coverage(env, checkpointed(env, task, cp(env, part, remaining_subsystems=list(remaining)), [], [trace]))

    pytest_q = json.dumps(["pytest", "-q"])
    claim("matching_execution_is_accepted", [["pytest", "-q"]], [pytest_q])
    claim("text_is_not_a_json_command", [["pytest", "-q"]], ["pytest -q"])
    claim("json_that_is_not_a_list", [["pytest", "-q"]], ['{"a": 1}'])
    claim("empty_command_list", [["pytest", "-q"]], ["[]"])
    claim("command_with_a_non_string_item", [["pytest", "-q"]], ["[1]"])
    claim("source_list_cannot_attest_a_test", [["source-list"]], [json.dumps(["source-list"])])
    claim("source_read_cannot_attest_a_test", [["source-read", NORMAL, "0"]], [json.dumps(["source-read", NORMAL, "0"])])
    claim("inert_isolation_cannot_attest_a_test", [["pytest", "-q"]], [pytest_q], isolation="inert-objects-no-code-execution")
    claim("another_command_was_executed", [["ruff", "check"]], [pytest_q])
    claim("a_test_with_no_receipt_at_all", [], [pytest_q],
          not_run=[{"test": "other suite", "reason": "isolation unavailable", "follow_up": "run"}], remaining=["core"])
    claim("a_declared_not_run_test_is_skipped", [["pytest", "-q"]], ["pytest -q"],
          not_run=[{"test": "pytest -q", "reason": "isolation unavailable", "follow_up": "run"}], remaining=["core"])
    claim("inventory_receipt_cannot_clear_source_list", [["source-list"]], [json.dumps(["source-list"])], isolation="inert-objects-no-code-execution")
    claim("inventory_receipt_cannot_clear_an_unexecuted_test", [["source-list"]], [json.dumps(["python", "unexecuted_test.py"])],
          isolation="inert-objects-no-code-execution")

    # runner receipts a disposition names (L188-197; INV-RESEARCH-003)
    def receipt_claim(name, prepare, path=NORMAL):
        env = build(api, ws, "receipt-" + name)
        part, task = assigned(env, "paths", generation=True, path=path)
        ref = evidence(env, "model says it ran")
        receipt = prepare(env, task)
        record = path_disposition(env, part["paths"][0], "semantic", ref, receipt_ids=[receipt])
        out["receipt_" + name] = with_coverage(env, checkpointed(env, task, cp(env, part, remaining_paths=[]), [record]))
        return env

    receipt_claim("successful_is_accepted", lambda env, task: env.service.execute(task, env.record["id"], ["fixture-inspection"])["id"])

    def blocked(env, task):
        env.service.runner = Runner(api, env.artifacts, blocked=True)
        return env.service.execute(task, env.record["id"], ["fixture-blocked-inspection"])["id"]

    def failed(env, task):
        env.service.runner = Runner(api, env.artifacts, passed=False, outcome="tests_failed")
        return env.service.execute(task, env.record["id"], ["fixture-failed-inspection"])["id"]

    def planted(field, value):
        def prepare(env, task):   # LABELLED: the stored receipt row is edited (no honest call path stores a foreign receipt)
            rid = env.service.execute(task, env.record["id"], ["fixture-inspection"])["id"]
            row = get(env.store, "research_receipts", rid)
            put(env.store, "research_receipts", rid, {**row, field: value})
            return rid
        return prepare

    def output_missing(env, task):
        rid = env.service.execute(task, env.record["id"], ["fixture-inspection"])["id"]
        output = get(env.store, "research_receipts", rid)["receipt"]["output_ref"]
        (env.artifacts.root / (output[7:] + ".txt")).unlink()
        return rid

    receipt_claim("blocked_runner", blocked)
    receipt_claim("not_passed_runner", failed)
    env = build(api, ws, "receipt-of-another-task")   # one running task per agent: the first task completes before the second is claimed
    first_part, first = assigned(env, "paths", generation=True, path=LINK)
    foreign = env.service.execute(first, env.record["id"], ["fixture-inspection"])["id"]
    env.workflow.complete(first, {"analysis": {"outcome": "analysis_rejected"}})
    part, task = assigned(env, "paths", generation=True, path=NORMAL, name="second")
    out["receipt_of_another_task"] = with_coverage(env, checkpointed(
        env, task, cp(env, part, remaining_paths=[]),
        [path_disposition(env, part["paths"][0], "semantic", evidence(env, "model says it ran"), receipt_ids=[foreign])]))
    receipt_claim("of_another_audit", planted("audit_id", "another-audit"))
    receipt_claim("of_another_generation", planted("generation", 99))
    receipt_claim("output_artifact_missing", output_missing)
    env = build(api, ws, "receipt-binary")
    part, task = assigned(env, "paths", generation=True, path=BINARY)
    receipt = env.service.execute(task, env.record["id"], ["fixture-inspection"])
    ref = receipt["receipt"]["output_ref"]
    out["receipt_binary_with_a_runner_receipt_is_accepted"] = with_coverage(env, checkpointed(
        env, task, cp(env, part, remaining_paths=[]),
        [path_disposition(env, BINARY, "binary", ref, method="fixture-inspection", receipt_ids=[receipt["id"]])]))
    out["receipt_view"] = receipt_view(get(env.store, "research_receipts", receipt["id"]))


def b3_planted_inventory(api, ws, out):
    # LABELLED trusted inventories the importer cannot produce: a gitlink, a UTF-8 file holding a NUL, an envelope that is not
    # base64 and an inventory artifact that was never stored (M7 plants a second audit the same way for the submodule case).
    def planted(name):
        env = build(api, ws, "planted-" + name, imported=False)
        entries = [api.InventoryEntry(b64(b"vendor/nested"), "160000", "b" * 40, None, None)]
        for raw, body in ((b"nul.bin", b"a\x00b"), (b"plain.txt", b"hello")):
            oid = hashlib.sha1(b"blob %d\0" % len(body) + body).hexdigest()
            ref = env.artifacts.put(api.canonical({"version": 1, "encoding": "base64", "bytes_sha256": "0" * 64, "data": b64(body)}), "fixture")["ref"]
            entries.append(api.InventoryEntry(b64(raw), "100644", oid, len(body), ref))
        entries.append(api.InventoryEntry(b64(b"bad.txt"), "100644", "c" * 40, 1, envelope_artifact(env, "not base64!", "fixture")))
        entries.append(api.InventoryEntry(b64(b"absent.txt"), "100644", "d" * 40, 1, INVENTED))
        audit_id, checkpoint, task = plant_audit(env, entries, name)
        return env, audit_id, checkpoint, task

    def claim(name, target, kind, **overrides):
        env, audit_id, checkpoint, task = planted(name)
        ref = evidence(env, "claimed reading")
        path = b64(target)
        record = path_disposition(env, path, kind, ref, **overrides)
        if overrides.get("receipt_ids") == "run":
            rid = env.service.execute(task, audit_id, ["fixture-inspection"])["id"]
            record = replace(record, receipt_ids=[rid])
        remaining = [p for p in checkpoint.paths if p != path] if kind not in ("unreviewed", "unavailable") else list(checkpoint.paths)
        result = checkpointed(env, task, replace(checkpoint, remaining_paths=remaining), [record])
        out["planted_" + name] = {**result, "rows": counts(env.store)}

    claim("submodule_semantic_claim", b"vendor/nested", "semantic")
    claim("submodule_unreviewed_is_skipped_before_the_checks", b"vendor/nested", "unreviewed", evidence_refs=[], justification="", symbols=[])
    claim("submodule_unavailable_is_skipped_before_the_checks", b"vendor/nested", "unavailable", evidence_refs=[], justification="", symbols=[])
    claim("utf8_file_with_a_nul_is_binary_for_a_semantic_claim", b"nul.bin", "semantic")
    claim("utf8_file_with_a_nul_and_a_runner_receipt_is_accepted", b"nul.bin", "binary", method="fixture-inspection", receipt_ids="run")
    claim("plain_text_semantic_claim_is_accepted", b"plain.txt", "semantic")
    claim("envelope_that_is_not_base64", b"bad.txt", "semantic")
    claim("inventory_artifact_that_was_never_stored", b"absent.txt", "semantic")
    claim("claim_with_a_known_link", b"plain.txt", "generated", links=[b64(b"nul.bin")])
    claim("claim_with_an_unknown_link", b"plain.txt", "generated", links=[b64(b"nul.binx")])


def b3_integrity_and_rollback(api, ws, out):
    # execution integrity is never a typed rejection, whatever the message says (M7 test_audit_checkpoint_outcomes.py)
    for failure in ("anchored_body_missing", "unanchored_body_modified", "unanchored_metadata_missing", "injected_permission_error"):
        env = build(api, ws, "integrity-" + failure)
        part, task = assigned(env, "paths", generation=True)
        ref = evidence(env, "one traced path")
        named = ref
        if failure == "anchored_body_missing":
            named = env.record["inventory"][0]["artifact_ref"]   # a VERIFIED inventory artifact the answer names
            (env.artifacts.root / (named[7:] + ".txt")).unlink()
        elif failure == "unanchored_body_modified":
            (env.artifacts.root / (ref[7:] + ".txt")).write_text("rewritten", encoding="utf-8")
        elif failure == "unanchored_metadata_missing":
            (env.artifacts.root / (ref[7:] + ".json")).unlink()
        else:
            inspect = env.artifacts.inspect

            def refusing(reference, inspect=inspect, ref=ref):
                if reference == ref:
                    raise PermissionError("injected artifact permission failure")   # LABELLED: injected, no real permission failure
                return inspect(reference)

            env.artifacts.inspect = refusing
        out["integrity_" + failure] = with_coverage(env, checkpointed(env, task, cp(env, part, remaining_paths=[]),
                                                                       [path_disposition(env, part["paths"][0], "semantic", named)]))

    # an ordinary store failure after the coverage rows were staged is not a refused draft, and commits nothing (M7
    # `test_an_ordinary_store_failure_is_not_retained_as_a_refused_draft[memory]`; the PostgreSQL run is another family)
    env = build(api, ws, "store-failure")
    part, task = assigned(env, "subsystems", generation=True)
    ref = evidence(env, "subsystem evidence")
    transaction = api.MemoryTransaction
    original = transaction.put

    def failing(self, bucket, key, body):
        if bucket == "research_checkpoints":
            raise StoreFault("injected store write failure")   # LABELLED: injected, no real outage
        return original(self, bucket, key, body)

    transaction.put = failing
    try:
        failed = checkpointed(env, task, cp(env, part), [], [analysis(env, ref)])
    finally:
        transaction.put = original
    out["store_failure_after_staged_rows_commits_nothing"] = {**failed, "rows": counts(env.store),
                                                              "partition_unchanged": get(env.store, "research_partitions", part["partition_id"]) == part}
    out["store_failure_then_the_owned_task_completes"] = env.workflow.complete(task, {"analysis": {"outcome": "analysis_rejected"}})["status"]

    # M7 `test_the_whole_valid_checkpoint_commits_in_one_transaction[memory]`
    env = build(api, ws, "whole-valid")
    part, task = assigned(env, "subsystems", generation=True)
    ref = evidence(env, "subsystem evidence")
    trace = analysis(env, ref)
    saved = checkpointed(env, task, cp(env, part), [], [trace])
    with env.store.transaction() as tx:
        out["whole_valid_checkpoint_commits_in_one_transaction"] = {
            **saved, "subsystem_rows": [r["record"] == asdict(trace) for r in tx.scan("research_subsystems")],
            "history_holds_it": any(r["record"] == asdict(trace) for r in tx.scan("research_evidence_history")),
            "partition_is_the_saved_body": tx.get("research_partitions", part["partition_id"])["generation"] == part["generation"] + 1,
            "checkpoint_rows": len(tx.scan("research_checkpoints")), "coverage": coverage_of(env)}

    # M7 `test_the_candidate_type_keeps_every_existing_contract_expectation`
    def typed(raiser):
        try:
            raiser("a candidate claim")
        except Exception as exc:   # the type is the characterized result
            return {"type": type(exc).__name__, "is_contract_error": isinstance(exc, api.ContractError),
                    "is_draft_rejection": isinstance(exc, api.AuditDraftRejected)}
        return None
    out["reject_is_typed_and_require_is_not"] = {
        "reject": typed(lambda text: api.reject(False, text)), "require": typed(lambda text: api.require(False, text)),
        "contract_error_subclass": issubclass(api.AuditDraftRejected, api.ContractError), "reject_true": api.reject(True, "x")}

    # checkpoint-only evidence survives a continuation and is required for adoption (M7 `test_checkpoint_only_evidence_...[4]`)
    for damage in ("missing", "corrupt"):
        for include_audit_id in (False, True):
            env = build(api, ws, "checkpoint-only-%s-%s" % (damage, include_audit_id))
            activate(env)
            named = evidence(env, "checkpoint-only evidence")
            part, task = assigned(env, "paths")
            first = env.service.checkpoint(task, cp(env, part, evidence_refs=[named]), [], [])
            continued = checkpointed(env, task, replace(api.PartitionCheckpoint(**first), evidence_refs=[]))
            env.workflow.complete(task, get(env.store, "research_partitions", part["partition_id"]))
            adopted = replace(complete_audit(env), decision="adapt")
            env.service.propose(env.record["id"], adopted)
            for actor in ("lead:research", "conductor"):
                approve(env, actor)
            case = {"continued": continued, "named_evidence_retained": named in get(env.store, "research_partitions", part["partition_id"])["evidence_refs"],
                    "eligible": coverage_of(env)["adoption_eligible"]}
            with env.store.transaction() as tx:
                approval = next(r for r in tx.scan("research_approvals") if r["audit_id"] == env.record["id"])
                details = {"proposal": approval["proposal"], "audit_approval": approval["binding"]}
                if include_audit_id:
                    details["audit_id"] = env.record["id"]
                case["inspect_approval_before_damage"] = outcome(api, api.inspect_approval, tx, details, env.artifacts)
            path = env.artifacts.root / (named[7:] + ".txt")
            if damage == "missing":
                path.unlink()
            else:
                path.write_text("tampered checkpoint evidence", encoding="utf-8")
            case["eligible_after_damage"] = coverage_of(env)["adoption_eligible"]
            with env.store.transaction() as tx:
                case["inspect_approval_after_damage"] = outcome(api, api.inspect_approval, tx, details, env.artifacts)
            out["checkpoint_only_evidence_%s_%s_audit_id" % (damage, "with" if include_audit_id else "without")] = case



# ---- b4: observed assets and coverage ----------------------------------------------------------------------------------------
def observed(env, path, state="unreviewed_observed_asset", basis="observed", sha="a" * 64, refs=()):
    """M7 `observed(path, state, basis, sha, refs)`: an `ObservedAsset` whose path is the Base64 of the text."""
    return env.api.ObservedAsset(b64(path.encode()), basis, state, sha, 10, list(refs))


def observed_view(result):
    return {"audit_id_is_the_audit": bool(result["audit_id"]), "changed": result["changed"], "total": result["total"],
            "pending": result["pending"], "pending_paths": result["pending_paths"], "states": result["states"]}


def b4_observed_coverage(api, ws):
    out = {}
    env = build(api, ws, "observed")
    activate(env)
    ref = evidence(env, "observed asset review")
    before = env.service.coverage(env.record["id"])
    out["coverage_before_any_asset"] = coverage_view(before)
    out["coverage_unknown_audit"] = step(env, env.service.coverage, "no-such-audit")
    first = step(env, env.service.observe_assets, env.record["id"], [
        observed(env, "notes/uncommitted.md"), observed(env, ".cache/index.json", "generated_cache_metadata_only", "cache", None),
        observed(env, "sessions/private.jsonl", "excluded_private_session_or_credential_surface", "private_session", None),
        observed(env, "vendor/nested/.git/HEAD", "acquisition_pending", "nested_repository", None)], view=observed_view)
    out["observe_four_assets"] = first
    after = env.service.coverage(env.record["id"])
    out["coverage_separate_ledger"] = {"git_denominator_untouched": after["remaining_paths"] == before["remaining_paths"],
                                      **coverage_view(after)}
    adopted = complete_audit(env)
    out["coverage_after_the_tracked_audit_is_complete"] = coverage_of(env)
    out["propose_blocked_by_pending_assets"] = step(env, env.service.propose, env.record["id"], adopted)
    out["observe_idempotent_reobservation_leaves_no_history"] = step(
        env, env.service.observe_assets, env.record["id"], [observed(env, "notes/uncommitted.md")], view=observed_view)
    out["observe_reviewed_without_evidence"] = step(env, env.service.observe_assets, env.record["id"],
                                                    [observed(env, "notes/uncommitted.md", "semantically_reviewed")])
    out["observe_dispositions_advance_with_evidence"] = step(env, env.service.observe_assets, env.record["id"], [
        observed(env, "notes/uncommitted.md", "semantically_reviewed", refs=[ref]),
        observed(env, "vendor/nested/.git/HEAD", "excluded_private_session_or_credential_surface", "nested_repository", None)],
        view=observed_view)
    out["coverage_whole_analysis_complete_with_every_asset_dispositioned"] = coverage_of(env)
    out["observe_cannot_regress_to_pending"] = step(env, env.service.observe_assets, env.record["id"], [observed(env, "notes/uncommitted.md")])
    with env.store.transaction() as tx:
        row = next(r for r in tx.scan("research_observed_assets") if r["record"]["path"] == observed(env, "notes/uncommitted.md").path)
        out["observe_history_keeps_the_prior_record"] = {"history_states": [h["state"] for h in row["history"]], "state": row["record"]["state"],
                                                         "keys": sorted(row), "id_is_the_digest": row["id"] == api.digest(
                                                             {"audit": env.record["id"], "path": row["record"]["path"]})}
    out["observe_tracked_path_belongs_to_the_inventory"] = step(
        env, env.service.observe_assets, env.record["id"], [api.ObservedAsset(NORMAL, "observed", "unreviewed_observed_asset", None, None, [])])
    for name, bad in (("unknown_basis", observed(env, "x", basis="mystery")), ("unknown_state", observed(env, "x", state="done")),
                      ("absolute_path", observed(env, "/abs")), ("dot_dot_path", observed(env, "a/../b")),
                      ("bad_hash", observed(env, "x", sha="zz"))):
        out["observe_invalid_" + name] = step(env, env.service.observe_assets, env.record["id"], [bad])
    # an open partition question keeps the completion verdict and the proposal gate in agreement (M7 review counterexample, PR #43)
    with env.store.transaction() as tx:
        partition = tx.scan("research_partitions")[0]
        partition["open_questions"] = ["Which runtime consumes this path?"]
        tx.put("research_partitions", partition["partition_id"], partition)
    out["coverage_open_question_keeps_the_analysis_incomplete"] = coverage_of(env)
    out["propose_blocked_by_an_open_question"] = step(env, env.service.propose, env.record["id"], adopted)
    with env.store.transaction() as tx:
        partition["open_questions"] = []
        tx.put("research_partitions", partition["partition_id"], partition)
    out["coverage_complete_again_without_the_question"] = coverage_of(env)
    out["propose_after_the_gates_clear"] = step(env, env.service.propose, env.record["id"], adopted)
    for actor in ("lead:research", "conductor"):
        approve(env, actor)
    out["coverage_eligible_after_both_approvals"] = coverage_of(env)
    out["observe_after_approval_changes_the_binding"] = step(env, env.service.observe_assets, env.record["id"], [observed(env, "notes/late.md")],
                                                            view=observed_view)
    out["coverage_not_eligible_after_a_late_asset"] = coverage_of(env)

    env = build(api, ws, "observed-refusals")
    ref = evidence(env, "observed evidence")
    modified = evidence(env, "will be modified")
    (env.artifacts.root / (modified[7:] + ".txt")).write_text("rewritten", encoding="utf-8")
    out["observe_empty_list"] = step(env, env.service.observe_assets, env.record["id"], [])
    out["observe_duplicate_paths"] = step(env, env.service.observe_assets, env.record["id"], [observed(env, "a"), observed(env, "a", "acquisition_pending")])
    out["observe_unknown_audit"] = step(env, env.service.observe_assets, "no-such-audit", [observed(env, "a")])
    out["observe_evidence_never_stored"] = step(env, env.service.observe_assets, env.record["id"],
                                                [observed(env, "a", "semantically_reviewed", refs=[INVENTED])])
    out["observe_evidence_modified"] = step(env, env.service.observe_assets, env.record["id"],
                                            [observed(env, "a", "semantically_reviewed", refs=[modified])])
    out["observe_new_pending_asset"] = step(env, env.service.observe_assets, env.record["id"], [observed(env, "a")], view=observed_view)
    out["observe_pending_to_another_pending_state_keeps_history"] = step(
        env, env.service.observe_assets, env.record["id"], [observed(env, "a", "acquisition_pending", sha=None)], view=observed_view)
    out["observe_second_pending_state"] = step(env, env.service.observe_assets, env.record["id"],
                                               [observed(env, "a", "requires_content_boundary_review", sha=None)], view=observed_view)
    out["observe_pending_to_final"] = step(env, env.service.observe_assets, env.record["id"],
                                           [observed(env, "a", "semantically_reviewed", refs=[ref])], view=observed_view)
    out["observe_final_to_another_final"] = step(env, env.service.observe_assets, env.record["id"],
                                                 [observed(env, "a", "generated_cache_metadata_only", "cache", None)], view=observed_view)
    with env.store.transaction() as tx:
        row = next(r for r in tx.scan("research_observed_assets"))
        out["observe_history_after_four_transitions"] = [h["state"] for h in row["history"]]
        # LABELLED: an observed asset of ANOTHER audit never enters this audit's ledger (no honest call path stores one)
        tx.put("research_observed_assets", "foreign", {"id": "foreign", "audit_id": "another-audit",
                                                       "record": asdict(observed(env, "elsewhere")), "history": [], "at": "x"})
    out["coverage_ignores_the_assets_of_another_audit"] = coverage_of(env)
    out["coverage_counts_every_state_of_this_audit"] = coverage_of(env)["observed_assets"]
    return out


# ---- b5: propose, execute, _queue_review -------------------------------------------------------------------------------------
def adaptation_view(body):
    return {"keys": sorted(body), "status": body["status"], "decision": body["proposal"]["decision"], "id_is_set": bool(body["id"]),
            "audit_id_is_set": bool(body["audit_id"])}


def decision_view_planted(row, key):
    return {"id_is_the_key": row["id"] == key, "actor": row["actor"], "phase": row["phase"], "status": row["status"], "attempt": row["attempt"],
            "input": row["input"], "message": [row["message"]["type"], row["message"]["who"], row["message"]["what"],
                                                row["message"]["correlation_id"]]}


def b5_propose_execute(api, ws):
    out = {}
    env = build(api, ws, "propose")
    audit_id = env.record["id"]
    for decision in ("defer", "reject"):
        result = step(env, env.service.propose, audit_id, proposal(env, decision=decision), view=adaptation_view)
        out["propose_%s_is_stored_deferred_without_a_gate" % decision] = result
    replay = step(env, env.service.propose, audit_id, proposal(env, decision="defer"), view=adaptation_view)
    out["propose_replay_is_idempotent"] = replay
    out["propose_defer_queues_no_review"] = {"decisions_pending": len(scan(env.store, "decisions_pending")),
                                             "adaptations": len(scan(env.store, "research_adaptations"))}
    for name, author in (("another_team_worker", "worker:implementation"), ("a_lead", "lead:research"), ("the_conductor", "conductor"),
                         ("an_unknown_actor", "nobody")):
        out["propose_author_" + name] = step(env, env.service.propose, audit_id, proposal(env, decision="defer", author=author))
    out["propose_unknown_audit"] = step(env, env.service.propose, "no-such-audit", proposal(env, decision="defer"))
    other_source = replace(env.source, repository=OTHER_REPO)
    out["propose_other_repository"] = step(env, env.service.propose, audit_id, proposal(env, decision="defer", source=other_source))
    out["propose_other_commit"] = step(env, env.service.propose, audit_id, proposal(env, decision="defer", source=replace(env.source, commit="9" * 40)))
    out["propose_unknown_scope"] = step(env, env.service.propose, audit_id, proposal(env, decision="defer", scope=[NORMAL, b64(b"never")]))
    out["propose_empty_scope_is_an_incomplete_mapping"] = step(env, env.service.propose, audit_id, proposal(env, decision="defer", scope=[]))
    out["propose_invalid_decision"] = step(env, env.service.propose, audit_id, proposal(env, decision="maybe"))
    for decision in ("adopt", "adapt"):
        out["propose_%s_before_any_coverage" % decision] = step(env, env.service.propose, audit_id, proposal(env, decision=decision))
    adopted = complete_audit(env)
    out["propose_adapt_without_an_active_evaluator"] = step(env, env.service.propose, audit_id, adopted)
    activate(env)
    queued = step(env, env.service.propose, audit_id, adopted, view=adaptation_view)
    out["propose_adapt_queues_the_lead_review"] = queued
    rows = scan(env.store, "decisions_pending")
    with env.store.transaction() as tx:
        gate_binding = api.binding(tx, audit_id, asdict(adopted))
    out["propose_queued_decision"] = {"count": len(rows), "rows": [decision_view(r) for r in rows],
                                      "binding_is_the_gate_binding": rows[0]["input"]["binding"] == gate_binding,
                                      "input_proposal_is_the_body": rows[0]["input"]["proposal"] == asdict(adopted)}
    out["propose_adapt_replay_queues_nothing_more"] = step(env, env.service.propose, audit_id, adopted, view=adaptation_view)
    out["propose_adopt_is_a_distinct_proposal_and_review"] = step(env, env.service.propose, audit_id, replace(adopted, decision="adopt"),
                                                                  view=adaptation_view)
    out["propose_two_decisions_queued"] = {"decisions_pending": len(scan(env.store, "decisions_pending")),
                                           "adaptations": len(scan(env.store, "research_adaptations"))}

    # `_queue_review` (L395-405) called as the proposal gate calls it
    env = build(api, ws, "queue-review")
    audit_id = env.record["id"]
    body = {"author": "worker:github", "decision": "adapt"}
    bound = "binding-1"
    key = api.digest({"binding": bound, "actor": "lead:research"})

    def queue(actor, binding=bound):
        with env.store.transaction() as tx:
            env.service._queue_review(tx, audit_id, body, binding, actor)

    out["queue_review_writes_one_pending_row"] = step(env, queue, "lead:research")
    out["queue_review_row"] = decision_view_planted(get(env.store, "decisions_pending", key), key)
    out["queue_review_is_idempotent"] = step(env, queue, "lead:research")
    row = get(env.store, "decisions_pending", key)
    put(env.store, "decisions_pending", key, {**row, "status": "running", "attempt": 3})
    out["queue_review_never_overwrites_an_existing_row"] = {**step(env, queue, "lead:research"),
                                                            "row_status": get(env.store, "decisions_pending", key)["status"]}
    out["queue_review_per_actor_and_binding"] = {**step(env, queue, "conductor"), "rows": len(scan(env.store, "decisions_pending"))}
    out["queue_review_another_binding"] = {**step(env, queue, "lead:research", "binding-2"), "rows": len(scan(env.store, "decisions_pending"))}

    # `execute` (L374-393)
    env = build(api, ws, "execute-no-runner", runner=False)
    part, task = assigned(env, "paths", name="no-runner")
    out["execute_without_a_runner"] = step(env, env.service.execute, task, env.record["id"], ["fixture-inspection"])

    env = build(api, ws, "execute")
    part, task = assigned(env, "paths")
    first = step(env, env.service.execute, task, env.record["id"], ["fixture-inspection"],
                 view=lambda r: {"id_is_the_digest": r["id"] == api.digest({k: v for k, v in r.items() if k != "id"}), "keys": sorted(r),
                                 "task_is_the_task": r["task_id"] == task["id"], "generation": r["generation"],
                                 **receipt_view(r)})
    out["execute_stores_a_runner_receipt"] = first
    again = step(env, env.service.execute, task, env.record["id"], ["fixture-inspection"])
    out["execute_same_command_again_is_the_same_receipt"] = {**again, "same_value": again["value"] == first["value"],
                                                            "receipts": len(scan(env.store, "research_receipts")),
                                                            "runner_calls": env.runner.calls}
    out["execute_another_command_is_another_receipt"] = {**step(env, env.service.execute, task, env.record["id"], ["fixture-other"]),
                                                         "receipts": len(scan(env.store, "research_receipts"))}
    out["execute_not_assigned_this_audit"] = step(env, env.service.execute, task, "another-audit", ["fixture-inspection"])
    env.workflow.complete(task, {"analysis": {"outcome": "analysis_rejected"}})
    out["execute_stale_task"] = step(env, env.service.execute, task, env.record["id"], ["fixture-inspection"])

    def one_case(name, runner=None, audit_details=None, command=("fixture-inspection",)):
        env = build(api, ws, "execute-" + name)
        if runner is not None:
            env.service.runner = runner(env)
        audit_id = audit_details or env.record["id"]
        task = assign(env, {"audit_id": audit_id}, name=name)
        result = step(env, env.service.execute, task, audit_id, list(command))
        out["execute_" + name] = {**result, "receipts": len(scan(env.store, "research_receipts"))}
        return env

    one_case("unknown_audit", audit_details="ghost-audit")
    one_case("runner_reports_another_source", runner=lambda env: Runner(
        api, env.artifacts, mutate=lambda r: replace(r, source=replace(r.source, repository=OTHER_REPO))))
    one_case("runner_reports_another_commit", runner=lambda env: Runner(
        api, env.artifacts, mutate=lambda r: replace(r, source=replace(r.source, commit="9" * 40))))
    one_case("runner_reports_an_invalid_source", runner=lambda env: Runner(
        api, env.artifacts, mutate=lambda r: replace(r, source=replace(r.source, repository=REPO + ".git"))))
    one_case("runner_reports_an_incomplete_receipt", runner=lambda env: Runner(api, env.artifacts, mutate=lambda r: replace(r, runner_id="")))
    one_case("runner_reports_a_passed_nonzero_receipt", runner=lambda env: Runner(
        api, env.artifacts, mutate=lambda r: replace(r, exit_status=1, passed=True)))
    one_case("runner_output_artifact_was_never_stored", runner=lambda env: Runner(api, env.artifacts, mutate=lambda r: replace(r, output_ref=INVENTED)))
    one_case("blocked_runner_receipt_is_stored", runner=lambda env: Runner(api, env.artifacts, blocked=True))
    one_case("unsuccessful_runner_receipt_is_stored", runner=lambda env: Runner(api, env.artifacts, passed=False, outcome="tests_failed"))

    def lose_lease(task, workflow):   # LABELLED: the lease is completed while the runner works
        workflow.complete(task, {"analysis": {"outcome": "analysis_rejected"}})

    one_case("lease_lost_while_the_runner_works", runner=lambda env: Runner(api, env.artifacts, hook=lose_lease))
    return out


# ---- b6: review and _eligible ------------------------------------------------------------------------------------------------
def proposed(api, ws, name, runner_kwargs=None):
    """An activated audit, completed under successful receipts and proposed for adoption (M7 `complete_fixture_audit` +
    `propose`); the reviews are the case's own."""
    env = build(api, ws, name)
    if runner_kwargs:
        env.service.runner = Runner(api, env.artifacts, **runner_kwargs)
    activate(env)
    adopted = complete_audit(env)
    env.service.propose(env.record["id"], adopted)
    return env, adopted


def approval_view(row):
    if row is None:
        return None
    return {"keys": sorted(row), "status": row["status"], "reviews": len(row["reviews"]), "binding_is_set": bool(row["binding"]),
            "revocations": len(row.get("revocations", [])), "revoked_by_is_set": bool(row.get("revoked_by"))}


def approvals_of(env):
    return [approval_view(r) for r in scan(env.store, "research_approvals")]


def rows_of(env):
    return {"reviews": [review_view(r) for r in sorted(scan(env.store, "research_reviews"), key=lambda r: (r["review"]["actor"], r["sequence"]))],
            "approvals": approvals_of(env), "decisions": [(r["actor"], r["status"]) for r in sorted(
                scan(env.store, "decisions_pending"), key=lambda r: (r["actor"], r["status"]))]}


def b6_review(api, ws):
    out = {}

    # the positive lifecycle (M7 `test_positive_lifecycle_dispatch_revalidation_and_rollback`: the module's part)
    env, adopted = proposed(api, ws, "review-lifecycle")
    out["lifecycle_not_eligible_after_the_proposal"] = coverage_of(env)["adoption_eligible"]
    lead = lease_review(env, "lead:research")
    review = independent_review(env, lead, "lead:research")
    out["lead_accepts_and_the_conductor_is_queued"] = reviewed(env, lead, review)
    queued = [decision_view(r) for r in scan(env.store, "decisions_pending") if r["actor"] == "conductor"]
    out["lead_acceptance_queued_decision"] = {"conductor_rows": queued, "approvals": approvals_of(env)}
    out["lifecycle_not_eligible_after_the_lead"] = coverage_of(env)["adoption_eligible"]
    conductor = lease_review(env, "conductor")
    cr = independent_review(env, conductor, "conductor")
    out["conductor_accepts_and_the_approval_is_recorded"] = reviewed(env, conductor, cr)
    out["approval_after_both_acceptances"] = rows_of(env)
    out["lifecycle_eligible_after_the_conductor"] = coverage_of(env)
    with env.store.transaction() as tx:
        approval = next(iter(tx.scan("research_approvals")))
        out["approval_row"] = {**approval_view(approval), "audit_id_is_set": bool(approval["audit_id"]),
                               "reviews_are_the_review_digests": sorted(approval["reviews"]) == sorted(
                                   api.digest(r["review"]) for r in tx.scan("research_reviews")),
                               "proposal_is_the_body": approval["proposal"] == asdict(adopted)}
        details = {"proposal": approval["proposal"], "audit_approval": approval["binding"]}
        out["require_adoption_admits_the_approval"] = outcome(api, api.require_adoption, tx, details, view=lambda a: approval_view(a))
    # a redelivery of the conductor's review is idempotent (L429-434)
    out["redelivery_returns_the_recorded_review"] = reviewed(env, conductor, cr)

    # unauthorized reviewer, self review, a stale binding, a missing receipt
    env, adopted = proposed(api, ws, "review-refusals")
    lead = lease_review(env, "lead:research")
    good = independent_review(env, lead, "lead:research")
    out["unauthorized_actor_spoof"] = reviewed(env, lead, replace(good, actor="conductor"))
    out["unauthorized_actor_outside_the_review_contract"] = reviewed(env, lead, replace(good, actor="worker:github"))
    with env.store.transaction() as tx:   # LABELLED: a decision of another phase (no honest call path leases one for this actor)
        row = tx.get("decisions_pending", lead["id"])
        tx.put("decisions_pending", lead["id"], {**row, "phase": "threshold_review"})
    out["unauthorized_other_phase"] = reviewed(env, lead, good)
    with env.store.transaction() as tx:
        row = tx.get("decisions_pending", lead["id"])
        tx.put("decisions_pending", lead["id"], {**row, "phase": "audit_review", "input": {
            **row["input"], "proposal": {**row["input"]["proposal"], "author": "lead:research"}}})
    out["self_review_by_the_proposal_author"] = reviewed(env, lead, good)   # LABELLED: the leased input names the reviewer as its author
    with env.store.transaction() as tx:
        row = tx.get("decisions_pending", lead["id"])
        tx.put("decisions_pending", lead["id"], {**row, "input": {**row["input"], "proposal": {**row["input"]["proposal"], "author": "worker:github"}}})
    out["stale_binding_that_is_not_the_leased_one"] = reviewed(env, lead, replace(good, binding="0" * 64))
    out["missing_receipt"] = reviewed(env, lead, replace(good, execution_id="no-such-receipt"))
    for name, field, value in (("another_audit", "audit_id", "another-audit"), ("another_generation", "generation", 99),
                               ("another_task", "task_id", "another-task")):
        rid = env.service.execute(lead, env.record["id"], ["fixture-" + name])["id"]
        row = get(env.store, "research_receipts", rid)
        put(env.store, "research_receipts", rid, {**row, field: value})   # LABELLED: no honest call path stores a foreign receipt
        out["receipt_of_" + name] = reviewed(env, lead, replace(good, execution_id=rid))
    out["rows_after_the_refusals"] = rows_of(env)
    with env.store.transaction() as tx:   # LABELLED: recovery state planted on the leased decision
        row = tx.get("decisions_pending", lead["id"])
        tx.put("decisions_pending", lead["id"], {**row, "recovery_sequence": 1})
    out["validate_decision_recovery_sequence_without_a_receipt"] = reviewed(env, lead, good)
    with env.store.transaction() as tx:
        row = tx.get("decisions_pending", lead["id"])
        tx.put("decisions_pending", lead["id"], {**row, "recovery_sequence": 0, "recovery_receipt": 5})
    out["validate_decision_receipt_reference_is_not_a_string"] = reviewed(env, lead, good)
    with env.store.transaction() as tx:
        row = tx.get("decisions_pending", lead["id"])
        tx.put("decisions_pending", lead["id"], {**row, "recovery_receipt": "no-such-recovery"})
    out["validate_decision_unknown_recovery_receipt"] = reviewed(env, lead, good)
    with env.store.transaction() as tx:
        row = tx.get("decisions_pending", lead["id"])
        budget_row = {k: v for k, v in row.items() if k != "recovery_receipt"}
        tx.put("decisions_pending", lead["id"], {**budget_row, "recovery_sequence": 0, "retry_budget": {"recovery_ref": "x"}})
    out["validate_decision_budget_names_a_recovery_without_a_receipt"] = reviewed(env, lead, good)
    with env.store.transaction() as tx:
        row = tx.get("decisions_pending", lead["id"])
        tx.put("decisions_pending", lead["id"], {k: v for k, v in row.items() if k not in ("retry_budget", "recovery_sequence")})
    out["review_after_the_planted_recovery_state_is_cleared"] = reviewed(env, lead, good)

    # an observed asset after the proposal changes the binding the leased decision carries
    env, adopted = proposed(api, ws, "review-stale")
    lead = lease_review(env, "lead:research")
    good = independent_review(env, lead, "lead:research")
    env.service.observe_assets(env.record["id"], [observed(env, "notes/late.md")])
    out["stale_binding_after_new_evidence"] = reviewed(env, lead, good)

    # blocked, unsuccessful and unreadable inspections
    for name, kwargs in (("blocked", {"blocked": True}), ("not_passed", {"passed": False, "outcome": "tests_failed"})):
        env, adopted = proposed(api, ws, "review-" + name)
        lead = lease_review(env, "lead:research")
        env.service.runner = Runner(api, env.artifacts, **kwargs)
        receipt = env.service.execute(lead, env.record["id"], ["fixture-" + name + "-inspection"])
        review = independent_review(env, lead, "lead:research", execution=receipt["id"])
        out["inspection_%s_cannot_approve" % name] = reviewed(env, lead, review)
        out["inspection_%s_may_reject_and_is_retained" % name] = reviewed(env, lead, replace(review, accepted=False))
        out["inspection_%s_rows" % name] = {**rows_of(env), "receipt_is_retained": get(env.store, "research_receipts", receipt["id"]) is not None}
    env, adopted = proposed(api, ws, "review-legacy-receipt")
    lead = lease_review(env, "lead:research")
    receipt = env.service.execute(lead, env.record["id"], ["fixture-legacy-inspection"])
    stored = get(env.store, "research_receipts", receipt["id"])
    legacy = {k: v for k, v in stored["receipt"].items() if k not in ("passed", "outcome")}   # LABELLED: a receipt without the runner's verdict
    put(env.store, "research_receipts", receipt["id"], {**stored, "receipt": legacy})
    out["inspection_without_a_verdict_cannot_approve"] = reviewed(env, lead, independent_review(env, lead, "lead:research", execution=receipt["id"]))
    env, adopted = proposed(api, ws, "review-output-missing")
    lead = lease_review(env, "lead:research")
    receipt = env.service.execute(lead, env.record["id"], ["fixture-inspection"])
    output = get(env.store, "research_receipts", receipt["id"])["receipt"]["output_ref"]
    (env.artifacts.root / (output[7:] + ".txt")).unlink()
    out["inspection_output_artifact_missing"] = reviewed(env, lead, independent_review(env, lead, "lead:research", execution=receipt["id"]))

    # a rejection with no approval, and a lead rejection before the conductor acted
    env, adopted = proposed(api, ws, "review-first-rejection")
    lead = lease_review(env, "lead:research")
    rejection = independent_review(env, lead, "lead:research", accepted=False)
    out["first_review_is_a_rejection"] = reviewed(env, lead, rejection)
    out["first_rejection_rows"] = rows_of(env)
    out["first_rejection_queues_no_conductor_review"] = [r["actor"] for r in scan(env.store, "decisions_pending")]

    # the conductor cannot approve without an accepting lead review (L457-460)
    env, adopted = proposed(api, ws, "review-no-lead")
    lead_row = scan(env.store, "decisions_pending")[0]
    with env.store.transaction() as tx:   # LABELLED: the conductor's decision queued with no lead acceptance behind it
        env.service._queue_review(tx, env.record["id"], lead_row["input"]["proposal"], lead_row["input"]["binding"], "conductor")
    conductor = lease_review(env, "conductor")
    out["conductor_without_a_lead_acceptance"] = reviewed(env, conductor, independent_review(env, conductor, "conductor"))
    out["conductor_without_a_lead_rows"] = rows_of(env)

    # a later rejection revokes the approval (M7 `test_later_rejecting_review_revokes_approval[2]`)
    for rejecting_actor in ("conductor", "lead:research"):
        env, adopted = proposed(api, ws, "review-revoke-" + rejecting_actor)
        tasks = {actor: approve(env, actor) for actor in ("lead:research", "conductor")}
        case = {"eligible_before": coverage_of(env)["adoption_eligible"]}
        with env.store.transaction() as tx:
            approval = next(r for r in tx.scan("research_approvals") if r["audit_id"] == env.record["id"])
            details = {"proposal": approval["proposal"], "audit_approval": approval["binding"]}
            case["status_before"] = approval["status"]
            case["require_adoption_before"] = outcome(api, api.require_adoption, tx, details, view=approval_view)
            reviews_before = len(tx.scan("research_reviews"))
        task, review = tasks[rejecting_actor]
        case["rejection"] = reviewed(env, task, replace(review, accepted=False))
        case["eligible_after"] = coverage_of(env)["adoption_eligible"]
        with env.store.transaction() as tx:
            revoked = tx.get("research_approvals", approval["binding"])
            rejection_record = max((r for r in tx.scan("research_reviews") if r["review"]["actor"] == rejecting_actor), key=lambda r: r["sequence"])
            case["revoked"] = {**approval_view(revoked), "revoked_by_is_the_rejection": revoked["revoked_by"] == api.digest(rejection_record["review"]),
                               "revoked_at_is_the_rejection_time": revoked["revoked_at"] == rejection_record["at"]}
            case["reviews_retained"] = [reviews_before, len(tx.scan("research_reviews"))]
            case["require_adoption_after"] = outcome(api, api.require_adoption, tx, details)
            tx.put("research_approvals", approval["binding"], {k: v for k, v in revoked.items() if k not in {"status", "revoked_by", "revoked_at"}})
            case["require_adoption_without_the_status_flag"] = outcome(api, api.require_adoption, tx, details)
        message = api.envelope("task.assign", "conductor", "lead:improvement", "plan", {"objective": "adopt", **details}, "fixture")
        case["dispatch_after_the_rejection"] = outcome(api, env.workflow.submit, message)
        out["rejection_revokes_" + rejecting_actor.replace(":", "_")] = case

    # replay ordering by sequence (M7 `test_replaying_an_old_acceptance_never_overturns_a_later_rejection`)
    env, adopted = proposed(api, ws, "review-replay")
    tasks = {actor: approve(env, actor) for actor in ("lead:research", "conductor")}
    task, review = tasks["conductor"]
    original = get(env.store, "research_reviews", api.digest(asdict(review)))
    rejected = reviewed(env, task, replace(review, accepted=False))
    out["replay_pass_then_reject"] = {"rejection": rejected, "eligible": coverage_of(env)["adoption_eligible"]}
    replayed = reviewed(env, task, review)
    out["replay_of_the_old_acceptance_keeps_its_order"] = {**replayed, "equals_the_original": replayed["review"].get("value") == canonical_digest(original),
                                                          "eligible": coverage_of(env)["adoption_eligible"]}
    out["replay_rows"] = rows_of(env)
    for name, changed in (("trailing_space", replace(review, license_assessment=review.license_assessment + " ")),
                          ("prefixed_text", replace(review, license_assessment="Re-read: " + review.license_assessment))):
        out["reworded_acceptance_is_not_a_new_inspection_" + name] = reviewed(env, task, changed)
    out["reworded_acceptance_rows"] = rows_of(env)
    fresh_receipt = env.service.execute(task, task["input"]["audit_id"], ["fixture-independent-inspection", "again"])
    out["fresh_inspection_reapproves_and_outranks_the_rejection"] = reviewed(env, task, replace(review, execution_id=fresh_receipt["id"]))
    out["fresh_inspection_rows"] = {**rows_of(env), "eligible": coverage_of(env)["adoption_eligible"]}

    # rejection then acceptance orders by sequence, not existence (M7 `test_rejection_then_acceptance_orders_by_sequence_not_existence`)
    env, adopted = proposed(api, ws, "review-sequence")
    lead_task, lead_review = approve(env, "lead:research")
    task = lease_review(env, "conductor")
    rejected_review = independent_review(env, task, "conductor", accepted=False)
    out["sequence_conductor_rejects_first"] = reviewed(env, task, rejected_review)
    out["sequence_not_eligible_after_the_rejection"] = coverage_of(env)["adoption_eligible"]
    out["sequence_changing_one_mind_on_the_same_inspection"] = reviewed(env, task, replace(rejected_review, accepted=True))
    again = env.service.execute(task, task["input"]["audit_id"], ["fixture-independent-inspection", "again"])
    out["sequence_acceptance_under_a_new_inspection"] = reviewed(env, task, replace(rejected_review, accepted=True, execution_id=again["id"]))
    out["sequence_eligible_after_the_new_acceptance"] = coverage_of(env)["adoption_eligible"]
    out["sequence_lead_rejection_revokes"] = reviewed(env, lead_task, replace(lead_review, accepted=False))
    out["sequence_rows"] = {**rows_of(env), "eligible": coverage_of(env)["adoption_eligible"]}
    b6_eligibility(api, ws, out)
    return out


def b6_eligibility(api, ws, out):
    # `_eligible` (L473-484) through `coverage`; M7 `test_approval_invalidated_by_changed_binding[6]`
    for change in ("graph", "evidence", "receipt", "review_receipt", "policy", "revision", "rollout_paused", "deployment_released"):
        env, adopted = proposed(api, ws, "eligible-" + change)
        for actor in ("lead:research", "conductor"):
            approve(env, actor)
        case = {"eligible_before": coverage_of(env)["adoption_eligible"]}
        with env.store.transaction() as tx:
            if change == "graph":
                tx.put("research_control", "graph", {"changed": True})
            elif change == "evidence":
                row = tx.scan("research_paths")[0]
                row["record"]["justification"] = "changed"
                tx.put("research_paths", api.digest({"audit": env.record["id"], "item": row["record"]["path"]}), row)
            elif change in ("receipt", "review_receipt"):
                key = (tx.scan("research_paths")[0]["record"]["receipt_ids"][0] if change == "receipt"
                       else tx.scan("research_reviews")[0]["review"]["execution_id"])
                row = tx.get("research_receipts", key)
                row["receipt"]["exit_status"] = 1
                tx.put("research_receipts", key, row)
            elif change == "policy":
                row = tx.get("releases", "rel-1")
                row["policy_hash"] = "changed"
                tx.put("releases", "rel-1", row)
            elif change == "revision":
                row = tx.get("deployment", "active")
                row["revision"] = "changed"
                tx.put("deployment", "active", row)
            elif change == "rollout_paused":
                tx.put("research_control", "activation", {"status": "paused", "release_id": "rel-1"})
            else:
                tx.put("deployment", "active", {"release_id": "changed"})
        case["eligible_after"] = coverage_of(env)["adoption_eligible"]
        out["eligible_after_" + change] = case

    for damage in ("missing", "corrupt"):
        env, adopted = proposed(api, ws, "eligible-inventory-" + damage)
        for actor in ("lead:research", "conductor"):
            approve(env, actor)
        path = env.artifacts.root / (env.record["inventory"][0]["artifact_ref"][7:] + ".txt")
        before = coverage_of(env)["adoption_eligible"]
        if damage == "missing":
            path.unlink()
        else:
            path.write_text("corrupted", encoding="utf-8")
        out["eligible_after_an_inventory_artifact_is_%s" % damage] = {"eligible_before": before, "eligible_after": coverage_of(env)["adoption_eligible"]}

    # M7 `test_host_output_digests_are_not_artifact_edges_but_declared_children_are[2]`: the module's part (a declared child artifact)
    for damage in ("missing", "corrupt"):
        env = build(api, ws, "eligible-child-" + damage)
        child = evidence(env, "retained child evidence")
        env.service.runner = Runner(api, env.artifacts, children=[child])
        activate(env)
        adopted = complete_audit(env)
        env.service.propose(env.record["id"], adopted)
        for actor in ("lead:research", "conductor"):
            approve(env, actor)
        before = coverage_of(env)["adoption_eligible"]
        path = env.artifacts.root / (child[7:] + ".txt")
        if damage == "missing":
            path.unlink()
        else:
            path.write_text("changed evidence", encoding="utf-8")
        out["eligible_after_a_declared_child_is_%s" % damage] = {"eligible_before": before, "eligible_after": coverage_of(env)["adoption_eligible"]}

    # M7 `test_corrupt_artifact_and_changed_provenance_block_dispatch`: the module's part
    env, adopted = proposed(api, ws, "eligible-provenance")
    for actor in ("lead:research", "conductor"):
        approve(env, actor)
    with env.store.transaction() as tx:
        approval = next(iter(tx.scan("research_approvals")))
        details = {"audit_id": env.record["id"], "audit_approval": approval["binding"]}
        out["provenance_of_another_repository"] = outcome(api, api.require_adoption, tx, {**details, "source_url": OTHER_REPO})
    (env.artifacts.root / (env.record["inventory"][0]["artifact_ref"][7:] + ".txt")).write_text("corrupted", encoding="utf-8")
    out["provenance_after_corruption"] = {"eligible": coverage_of(env)["adoption_eligible"]}
    with env.store.transaction() as tx:
        out["provenance_inspect_approval_refuses_the_corruption"] = outcome(api, api.inspect_approval, tx, details, env.artifacts)

    # approvals that are not this audit's, and bad ones the loop steps over
    env, adopted = proposed(api, ws, "eligible-planted")
    with env.store.transaction() as tx:   # LABELLED rows: no honest call path stores an approval of another audit or a malformed one
        tx.put("research_approvals", "foreign-binding", {"audit_id": "another-audit", "binding": "foreign-binding", "status": "approved",
                                                         "reviews": [], "proposal": {}})
    out["eligible_ignores_the_approval_of_another_audit"] = coverage_of(env)["adoption_eligible"]
    with env.store.transaction() as tx:
        tx.put("research_approvals", "incomplete-binding", {"audit_id": env.record["id"], "binding": "incomplete-binding", "status": "approved",
                                                            "reviews": [], "proposal": {}})
    out["eligible_over_an_incomplete_approval"] = coverage_of(env)["adoption_eligible"]
    for actor in ("lead:research", "conductor"):
        approve(env, actor)
    out["eligible_steps_over_a_bad_approval_to_the_good_one"] = coverage_of(env)["adoption_eligible"]
    with env.store.transaction() as tx:
        tx.put("research_approvals", "malformed", {"audit_id": env.record["id"]})
    out["eligible_over_a_malformed_approval_row"] = outcome(api, env.service.coverage, env.record["id"], view=lambda c: c["adoption_eligible"])


# ---- coverage ------------------------------------------------------------------------------------------------------------------
B1, B2, B3, B4, B5, B6 = ("b1_backlog_import.", "b2_partition.", "b3_checkpoint.", "b4_observed_coverage.", "b5_propose_execute.", "b6_review.")


def at(prefix, *names):
    return [prefix + n for n in names]


# Every `require(...)`/`reject(...)` site of M7 `application/research.py` @ e38aa722 (44) and its one `raise`, keyed by source line:
# the cases that make the refusal. A pointer is checked at run time (a pointer that does not resolve is a driver error).
RAISES = {
    "39 require Backlog manifest mismatch": at(B1, "seed_manifest_mismatch_repository", "seed_manifest_mismatch_revision",
                                               "seed_manifest_mismatch_duplicate_path", "seed_manifest_mismatch_file_count"),
    "55 require Missing historical reference audit for backlog": at(B1, "seed_without_a_historical_audit", "seed_with_a_history_row_lacking_the_manifest"),
    "68 require Source verifier unavailable": at(B1, "import_without_a_verifier"),
    "69 require Explicit unique subsystem inventory required": at(B1, "import_subsystems_empty", "import_subsystems_duplicate", "import_subsystems_blank"),
    "78 require Conflicting audit import": at(B1, "import_conflicting_record"),
    "84 require Invalid partition budget": at(B2, "invalid_budget_zero", "invalid_budget_negative", "invalid_budget_over_128", "invalid_budget_bool",
                                               "invalid_budget_string", "invalid_budget_float", "invalid_budget_none"),
    "87 require Unknown audit (partition)": at(B2, "unknown_audit"),
    "120 require Audit source manifest unavailable": at(B2, "anchors_without_manifest_ref", "anchors_empty_source", "anchors_no_source") + at(
        B3, "audit_source_without_a_manifest_is_a_trusted_failure"),
    "146 raise AuditDraftRejected Claimed evidence artifact is absent": at(B2, "claimed_unanchored_absent_is_the_one_typed_raise") + at(
        B3, "claim_invented_evidence", "claim_invented_checkpoint_evidence"),
    "162 require Execution is not assigned this partition": at(B3, "trusted_foreign_assignment", "trusted_foreign_audit"),
    "166 require Stale partition writer": at(B3, "resume_replay_is_a_stale_partition_writer", "trusted_stale_generation",
                                              "stale_partition_that_does_not_exist", "stale_partition_of_another_audit"),
    "168 require Partition scope changed": at(B3, "scope_emptying_the_scope_is_a_scope_change", "trusted_changed_scope"),
    "171 require Unknown audit (checkpoint)": at(B3, "unknown_audit_behind_an_assigned_partition"),
    "178 reject Duplicate coverage": at(B3, "claim_duplicate_records", "scope_duplicate_path_records_are_a_typed_rejection",
                                         "valid_owner_duplicate_paths", "valid_owner_duplicate_subsystems"),
    "184 reject Cross-partition evidence": at(B3, "claim_foreign_record", "claim_foreign_subsystem"),
    "191 reject Runner receipt missing, stale, blocked or unsuccessful": at(
        B3, "forged_receipt_cannot_advance_the_checkpoint", "claim_missing_receipt_claim", "claim_unsupported_binary_claim", "receipt_blocked_runner",
        "receipt_not_passed_runner", "receipt_of_another_task", "receipt_of_another_audit", "receipt_of_another_generation"),
    "202 reject Submodule requires its own verified audit": at(B3, "planted_submodule_semantic_claim"),
    "210 reject Binary coverage requires verified runner inspection": at(B3, "claim_binary_without_receipt",
                                                                          "planted_utf8_file_with_a_nul_is_binary_for_a_semantic_claim"),
    "215 reject Unknown generator/original path": at(B3, "claim_display_name_link", "claim_unknown_link_identity", "planted_claim_with_an_unknown_link"),
    "217 reject Unknown subsystem path": at(B3, "claim_unknown_subsystem_path"),
    "228 reject Claimed test lacks matching successful execution command": at(
        B3, "test_claim_text_is_not_a_json_command", "test_claim_json_that_is_not_a_list", "test_claim_empty_command_list",
        "test_claim_command_with_a_non_string_item", "test_claim_source_list_cannot_attest_a_test", "test_claim_source_read_cannot_attest_a_test",
        "test_claim_inert_isolation_cannot_attest_a_test", "test_claim_another_command_was_executed", "test_claim_a_test_with_no_receipt_at_all",
        "test_claim_inventory_receipt_cannot_clear_source_list", "test_claim_inventory_receipt_cannot_clear_an_unexecuted_test"),
    "246 reject Remaining work does not reconcile": at(B3, "late_reconciliation_rejection", "reconcile_claims_the_dispositioned_path_still_remains",
                                                        "reconcile_claims_a_partial_scope_remains", "scope_dropping_remaining_work_does_not_reconcile"),
    "259 require Invalid audit continuation": at(B3, "continuation_sender_is_not_the_task_agent", "continuation_other_audit",
                                                  "continuation_other_partition", "continuation_without_details"),
    "297 require Unique observed asset paths required": at(B4, "observe_empty_list", "observe_duplicate_paths"),
    "303 require Unknown audit (observe_assets)": at(B4, "observe_unknown_audit"),
    "307 require Tracked Git paths belong to the inventory": at(B4, "observe_tracked_path_belongs_to_the_inventory"),
    "315 require Observed asset disposition cannot regress to pending": at(B4, "observe_cannot_regress_to_pending"),
    "328 require Unknown audit (coverage)": at(B4, "coverage_unknown_audit"),
    "350 require Research proposal author required": at(B5, "propose_author_another_team_worker"),
    "354 require Cross-repository proposal": at(B5, "propose_unknown_audit", "propose_other_repository", "propose_other_commit"),
    "356 require Unknown proposal scope": at(B5, "propose_unknown_scope"),
    "363 require Audit coverage incomplete": at(B5, "propose_adapt_before_any_coverage", "propose_adopt_before_any_coverage") + at(
        B3, "unexecuted_subsystem_without_receipt.propose_refused", "unexecuted_subsystem_with_receipt.propose_refused"),
    "365 require Observed assets await disposition": at(B4, "propose_blocked_by_pending_assets"),
    "367 require Open audit questions remain": at(B4, "propose_blocked_by_an_open_question"),
    "376 require Isolated runner unavailable": at(B5, "execute_without_a_runner"),
    "380 require Execution is not assigned this audit": at(B5, "execute_not_assigned_this_audit"),
    "382 require Unknown audit (execute)": at(B5, "execute_unknown_audit"),
    "385 require Runner source mismatch": at(B5, "execute_runner_reports_another_source", "execute_runner_reports_another_commit"),
    "414 require Unauthorized audit reviewer": at(B6, "unauthorized_actor_spoof.review", "unauthorized_other_phase.review"),
    "417 require Self review forbidden": at(B6, "self_review_by_the_proposal_author.review"),
    "418 require Stale audit review": at(B6, "stale_binding_that_is_not_the_leased_one.review", "stale_binding_after_new_evidence.review"),
    "421 require Independent command inspection required": at(B6, "missing_receipt.review", "receipt_of_another_audit.review",
                                                               "receipt_of_another_generation.review", "receipt_of_another_task.review"),
    "426 require Inspection-blocked review cannot approve / Inspection did not pass": at(
        B6, "inspection_blocked_cannot_approve.review", "inspection_not_passed_cannot_approve.review", "inspection_without_a_verdict_cannot_approve.review"),
    "441 require Re-approval requires a new inspection execution": at(
        B6, "reworded_acceptance_is_not_a_new_inspection_trailing_space.review", "reworded_acceptance_is_not_a_new_inspection_prefixed_text.review",
        "sequence_changing_one_mind_on_the_same_inspection.review"),
    "458 require Research lead approval required": at(B6, "conductor_without_a_lead_acceptance.review"),
}
AUDITS = "tests/test_research_audits.py"
OUTCOMES = "tests/test_audit_checkpoint_outcomes.py"


def other(module, *cases):
    """A test whose subject (or part of it) is another module: the cases of the part this module decides, if any."""
    return {"other family": module, **({"cases": list(cases)} if cases else {})}


M7_AUDITS = {   # tests/test_research_audits.py @ e38aa722: 45 test functions
    "test_git_inventory_preserves_raw_paths_binary_and_symlink": other("adapters.source_verification (Git inventory: raw paths, binary, symlink)") | {
        "cases": at(B1, "import_fresh", "import_replay_identical", "import_stored_record") + at(B4, "coverage_before_any_asset")},
    "test_inert_reader_never_executes_repository_code": other("adapters.audit_runner"),
    "test_oversized_source_line_advances_without_losing_unicode": other("adapters.audit_runner"),
    "test_changed_source_fails_even_with_rehashed_manifest": other("adapters.source_verification"),
    "test_artifact_corruption_rejected": other("adapters.source_verification"),
    "test_checkpoint_resume_and_stale_writer": at(B3, "resume_saves_generation_one", "resume_coverage_after_one_path",
                                                   "resume_replay_is_a_stale_partition_writer", "resume_after_the_lease_generation_moved"),
    "test_cannot_drop_scope_or_duplicate_coverage": at(B3, "scope_dropping_remaining_work_does_not_reconcile", "scope_emptying_the_scope_is_a_scope_change",
                                                        "scope_duplicate_path_records_are_a_typed_rejection", "scope_rows_after_the_refusals"),
    "test_readme_feed_discovery_never_queues_approval": other("application.workflow (discovery)"),
    "test_direct_dispatch_rejects_legacy_and_self_attested_approval": other("application.workflow, domain.research.require_dispatch"),
    "test_incident_plan_preserved": other("application.workflow"),
    "test_backlog_idempotent_and_preserves_legacy": at(B1, "seed_backlog_first", "seed_backlog_replay_is_identical", "seed_backlog_preserves_legacy"),
    "test_forged_receipt_cannot_advance_checkpoint": at(B3, "forged_receipt_cannot_advance_the_checkpoint"),
    "test_strict_wire_contract_rejects_unknown_fields_and_coercion": at(
        B3, "wire_source_identity_round_trips", "wire_version_is_a_bool", "wire_commit_is_an_int", "wire_unknown_field", "wire_missing_field"),
    "test_missing_execution_and_unresolved_subsystems_stay_remaining": at(
        B3, "unresolved_missing_execution_cannot_validate", "unresolved_explained_not_run_validates", "unresolved_planted_row_stays_remaining",
        "subsystem_tests_not_run", "subsystem_contradictions", "subsystem_unresolved_dependencies"),
    "test_unexecuted_subsystem_persists_but_cannot_complete_or_adopt[False]": at(B3, "unexecuted_subsystem_without_receipt"),
    "test_unexecuted_subsystem_persists_but_cannot_complete_or_adopt[True]": at(B3, "unexecuted_subsystem_with_receipt"),
    "test_checkpoint_history_retains_transitive_evidence": other("adapters.maintenance (ArtifactMaintenance.collect retains the transitive evidence)") | {
        "cases": at(B3, "history_retains_the_named_evidence")},
    "test_positive_lifecycle_dispatch_revalidation_and_rollback[False]": other("application.scheduling, application.releases (dispatch, rollback)") | {
        "cases": at(B6, "lifecycle_not_eligible_after_the_proposal", "lead_accepts_and_the_conductor_is_queued", "lifecycle_not_eligible_after_the_lead",
                    "conductor_accepts_and_the_approval_is_recorded", "lifecycle_eligible_after_the_conductor", "approval_row",
                    "require_adoption_admits_the_approval")},
    "test_positive_lifecycle_dispatch_revalidation_and_rollback[True]": other("application.scheduling, application.releases (dispatch, rollback)") | {
        "cases": at(B6, "lifecycle_eligible_after_the_conductor", "approval_row")},
    "test_host_output_digests_are_not_artifact_edges_but_declared_children_are[missing]": other("adapters.source_execution (DockerSourceRunner output)") | {
        "cases": at(B6, "eligible_after_a_declared_child_is_missing")},
    "test_host_output_digests_are_not_artifact_edges_but_declared_children_are[corrupt]": other("adapters.source_execution (DockerSourceRunner output)") | {
        "cases": at(B6, "eligible_after_a_declared_child_is_corrupt")},
    "test_checkpoint_only_evidence_survives_continuation_and_is_required_for_adoption[missing-False]": at(B3, "checkpoint_only_evidence_missing_without_audit_id"),
    "test_checkpoint_only_evidence_survives_continuation_and_is_required_for_adoption[missing-True]": at(B3, "checkpoint_only_evidence_missing_with_audit_id"),
    "test_checkpoint_only_evidence_survives_continuation_and_is_required_for_adoption[corrupt-False]": at(B3, "checkpoint_only_evidence_corrupt_without_audit_id"),
    "test_checkpoint_only_evidence_survives_continuation_and_is_required_for_adoption[corrupt-True]": at(B3, "checkpoint_only_evidence_corrupt_with_audit_id"),
    "test_approval_invalidated_by_changed_binding": at(B6, "eligible_after_graph", "eligible_after_evidence", "eligible_after_receipt",
                                                       "eligible_after_review_receipt", "eligible_after_policy", "eligible_after_revision"),
    "test_observed_assets_are_a_separate_completeness_ledger": at(
        B4, "coverage_before_any_asset", "observe_four_assets", "coverage_separate_ledger", "propose_blocked_by_pending_assets",
        "observe_idempotent_reobservation_leaves_no_history", "observe_reviewed_without_evidence", "observe_dispositions_advance_with_evidence",
        "coverage_whole_analysis_complete_with_every_asset_dispositioned", "observe_cannot_regress_to_pending", "observe_history_keeps_the_prior_record",
        "observe_tracked_path_belongs_to_the_inventory", "observe_invalid_unknown_basis", "observe_invalid_unknown_state", "observe_invalid_absolute_path",
        "observe_invalid_dot_dot_path", "observe_invalid_bad_hash", "coverage_open_question_keeps_the_analysis_incomplete",
        "propose_blocked_by_an_open_question", "coverage_complete_again_without_the_question", "propose_after_the_gates_clear",
        "coverage_eligible_after_both_approvals", "observe_after_approval_changes_the_binding", "coverage_not_eligible_after_a_late_asset"),
    "test_later_rejecting_review_revokes_approval[conductor]": at(B6, "rejection_revokes_conductor"),
    "test_later_rejecting_review_revokes_approval[lead:research]": at(B6, "rejection_revokes_lead_research"),
    "test_replaying_an_old_acceptance_never_overturns_a_later_rejection": at(
        B6, "replay_pass_then_reject", "replay_of_the_old_acceptance_keeps_its_order", "replay_rows",
        "reworded_acceptance_is_not_a_new_inspection_trailing_space", "reworded_acceptance_is_not_a_new_inspection_prefixed_text",
        "fresh_inspection_reapproves_and_outranks_the_rejection", "fresh_inspection_rows"),
    "test_rejection_then_acceptance_orders_by_sequence_not_existence": at(
        B6, "sequence_conductor_rejects_first", "sequence_not_eligible_after_the_rejection", "sequence_changing_one_mind_on_the_same_inspection",
        "sequence_acceptance_under_a_new_inspection", "sequence_eligible_after_the_new_acceptance", "sequence_lead_rejection_revokes", "sequence_rows"),
    "test_blocked_inspection_and_actor_spoof_cannot_approve": at(
        B6, "unauthorized_actor_spoof", "inspection_blocked_cannot_approve", "inspection_blocked_may_reject_and_is_retained", "inspection_blocked_rows"),
    "test_scheduler_deduplicates_and_resumes_checkpoint_generation": other("application.scheduling (schedule_audits)") | {
        "cases": at(B3, "context_exhaustion_retains_every_remaining_path", "context_exhaustion_second_checkpoint", "context_exhaustion_coverage")},
    "test_narrowed_scheduling_covers_one_audit_and_leaves_other_queues_untouched": other("application.scheduling (schedule_audits)"),
    "test_real_runner_failure_retains_command_evidence": other("adapters.audit_runner"),
    "test_audit_activation_requires_candidate_checks_and_is_atomic": other("application.releases"),
    "test_corrupt_artifact_and_changed_provenance_block_dispatch": other("application.audit_gate (require_adoption, inspect_approval), already moved") | {
        "cases": at(B6, "provenance_of_another_repository", "provenance_after_corruption", "provenance_inspect_approval_refuses_the_corruption",
                    "eligible_after_an_inventory_artifact_is_missing", "eligible_after_an_inventory_artifact_is_corrupt")},
    "test_namespace_denial_preserves_evidence_and_never_changes_isolation": other("adapters.audit_runner"),
    "test_acquire_pins_objects_without_checkout": other("adapters.audit_runner (acquire)"),
    "test_reconcile_after_incumbent_promotion_preserves_pause": other("application.releases (reconcile_audits)"),
    "test_reconcile_refuses_missing_canary": other("application.releases (reconcile_audits)"),
    "test_host_request_deduplicates_and_rejects_cross_source": other("application.source_execution"),
    "test_host_result_preserves_evidence_but_cannot_cross_invalidated_authority[pause]": other("application.source_execution"),
    "test_host_result_preserves_evidence_but_cannot_cross_invalidated_authority[lease]": other("application.source_execution"),
    "test_host_result_preserves_evidence_but_cannot_cross_invalidated_authority[deployment]": other("application.source_execution"),
    "test_host_queue_pause_cancels_pending_without_execution": other("application.source_execution"),
    "test_completed_host_receipt_rechecks_deployment_on_consumption": other("application.source_execution"),
    "test_inventory_receipt_cannot_clear_claimed_test_coverage[source-list]": at(B3, "test_claim_inventory_receipt_cannot_clear_source_list"),
    "test_inventory_receipt_cannot_clear_claimed_test_coverage[python]": at(B3, "test_claim_inventory_receipt_cannot_clear_an_unexecuted_test"),
    "test_host_restart_reclaims_expired_runner_and_fences_late_result": other("application.source_execution"),
    "test_docker_source_runner_uses_only_inert_source_and_immutable_image": other("adapters.source_execution"),
    "test_rollback_between_audit_releases_keeps_dispatch_paused[False]": other("application.releases, application.scheduling"),
    "test_rollback_between_audit_releases_keeps_dispatch_paused[True]": other("application.releases, application.scheduling"),
    "test_schema_preflight_failure_cannot_create_audit_success[proposal]": other("adapters.audit_execution, adapters.app_server"),
    "test_schema_preflight_failure_cannot_create_audit_success[review]": other("adapters.audit_execution, adapters.app_server"),
    "test_affected_records_still_validate_and_parse": other("adapters.audit_execution (typed_schema)") | {
        "cases": at(B3, "wire_AdaptationProposal_round_trips_and_refuses_other_versions", "wire_IndependentReview_round_trips_and_refuses_other_versions")},
    "test_execution_scopes_output_and_checkpoints_partial_progress[paths]": other("adapters.audit_execution (scoped output schema)") | {
        "cases": at(B3, "claim_foreign_record", "context_exhaustion_retains_every_remaining_path")},
    "test_execution_scopes_output_and_checkpoints_partial_progress[subsystems]": other("adapters.audit_execution (scoped output schema)") | {
        "cases": at(B3, "claim_foreign_subsystem", "whole_valid_checkpoint_commits_in_one_transaction")},
}
M7_OUTCOMES = {   # tests/test_audit_checkpoint_outcomes.py @ e38aa722: 19 test functions
    "test_every_candidate_relationship_claim_is_a_typed_rejection_that_commits_nothing": at(
        B3, "claim_duplicate_records", "claim_foreign_record", "claim_display_name_link", "claim_unknown_link_identity", "claim_invented_evidence",
        "claim_invented_checkpoint_evidence", "claim_binary_without_receipt", "claim_unsupported_binary_claim", "claim_missing_receipt_claim"),
    "test_subsystem_trace_claims_are_typed_rejections_that_commit_nothing": at(
        B3, "claim_unknown_subsystem_path", "test_claim_inert_isolation_cannot_attest_a_test"),
    "test_a_submodule_classification_claim_is_a_typed_rejection": at(B3, "planted_submodule_semantic_claim"),
    "test_a_late_reconciliation_rejection_rolls_back_rows_it_already_staged": at(
        B3, "late_reconciliation_rejection", "late_reconciliation_honest_version_checkpoints"),
    "test_the_owned_task_can_still_be_completed_after_a_rejection_rolled_back": at(B3, "rejection_leaves_the_task_completable"),
    "test_a_refused_candidate_claim_is_retained_analysis_rejected_not_a_failure": other("adapters.audit_execution (AuditExecution catches AuditDraftRejected)") | {
        "cases": at(B3, "claim_display_name_link", "claim_unknown_subsystem_path", "claim_invented_evidence", "claim_missing_receipt_claim",
                    "claim_binary_without_receipt")},
    "test_valid_and_justified_partial_work_still_checkpoints_through_the_same_boundary": other("adapters.audit_execution") | {
        "cases": at(B3, "reconcile_accepts_an_exact_account", "receipt_successful_is_accepted")},
    "test_execution_integrity_failures_are_never_retained_as_a_rejected_draft": at(
        B3, "integrity_anchored_body_missing", "integrity_unanchored_body_modified", "integrity_unanchored_metadata_missing",
        "integrity_injected_permission_error"),
    "test_an_ordinary_contract_error_with_a_candidate_message_is_not_an_analysis_outcome": other("adapters.audit_execution") | {
        "cases": at(B3, "reject_is_typed_and_require_is_not")},
    "test_trusted_anchor_failures_stay_ordinary_execution_failures": at(B3, "trusted_stale_generation", "trusted_changed_scope", "trusted_foreign_assignment"),
    "test_a_duplicate_draft_from_an_untrusted_execution_fails_as_execution_integrity": at(
        B3, "trusted_stale_ownership_with_duplicate_claims_is_still_the_trusted_failure", "trusted_stale_generation_with_duplicate_claims_is_still_the_trusted_failure",
        "trusted_changed_scope_with_duplicate_claims_is_still_the_trusted_failure", "trusted_foreign_assignment_with_duplicate_claims_is_still_the_trusted_failure"),
    "test_a_valid_owner_submitting_duplicates_is_still_a_typed_rejection_that_commits_nothing": at(
        B3, "valid_owner_duplicate_paths", "valid_owner_duplicate_subsystems", "valid_owner_lease_untouched_by_the_rejections"),
    "test_a_refused_candidate_partition_is_followed_by_a_valid_one_and_is_never_retried": other("adapters.audit_service"),
    "test_an_unbindable_refused_candidate_still_stops_the_service": other("adapters.audit_service"),
    "test_a_late_typed_rejection_rolls_back_then_the_owned_task_still_completes[memory]": at(
        B3, "late_reconciliation_rejection", "rejection_leaves_the_task_completable"),
    "test_a_late_typed_rejection_rolls_back_then_the_owned_task_still_completes[postgres]": other("PostgreSQL store (the integration run; this scenario uses MemoryStore)"),
    "test_an_ordinary_store_failure_is_not_retained_as_a_refused_draft[memory]": at(
        B3, "store_failure_after_staged_rows_commits_nothing", "store_failure_then_the_owned_task_completes"),
    "test_an_ordinary_store_failure_is_not_retained_as_a_refused_draft[postgres]": other("PostgreSQL store (the integration run; this scenario uses MemoryStore)"),
    "test_the_whole_valid_checkpoint_commits_in_one_transaction[memory]": at(B3, "whole_valid_checkpoint_commits_in_one_transaction"),
    "test_the_whole_valid_checkpoint_commits_in_one_transaction[postgres]": other("PostgreSQL store (the integration run; this scenario uses MemoryStore)"),
    "test_the_model_instructions_state_the_path_reference_contract_once": other("adapters.audit_execution"),
    "test_the_candidate_type_keeps_every_existing_contract_expectation": at(B3, "reject_is_typed_and_require_is_not"),
}


def resolve(result, path):
    node = result
    for part in path.split("."):
        node = node[part]   # a pointer that does not resolve is a driver error, never a silent gap
    return node


def pointers(entry):
    return entry if isinstance(entry, list) else entry.get("cases", [])


def coverage(result) -> dict:
    for table in (RAISES, M7_AUDITS, M7_OUTCOMES):
        for entry in table.values():
            for pointer in pointers(entry):
                resolve(result, pointer)
    unreachable = sorted(p for table in (RAISES, M7_AUDITS, M7_OUTCOMES) for entry in table.values() for p in pointers(entry)
                         if isinstance(resolve(result, p), dict) and "unreachable" in resolve(result, p))
    other_family = {name: entry["other family"] for table in (M7_AUDITS, M7_OUTCOMES) for name, entry in table.items()
                    if isinstance(entry, dict)}
    mirrored = sorted(name for table in (M7_AUDITS, M7_OUTCOMES) for name, entry in table.items() if pointers(entry))
    return {"raises": RAISES, "m7_test_research_audits": M7_AUDITS, "m7_test_audit_checkpoint_outcomes": M7_OUTCOMES,
            "other_family": other_family, "mirrored_node_ids": mirrored,
            "unreachable": {p: resolve(result, p)["unreachable"] for p in unreachable},
            "counts": {"require_reject_sites_in_the_module": 44, "raise_sites_in_the_module": 1,
                       "entries_for_sites_and_raise": len(RAISES),
                       "m7_test_research_audits_functions": 45, "m7_test_audit_checkpoint_outcomes_functions": 19,
                       "m7_node_ids": len(M7_AUDITS) + len(M7_OUTCOMES), "other_family_node_ids": len(other_family)}}


GROUPS = (("b1_backlog_import", b1_backlog_import), ("b2_partition", b2_partition), ("b3_checkpoint", b3_checkpoint),
          ("b4_observed_coverage", b4_observed_coverage), ("b5_propose_execute", b5_propose_execute), ("b6_review", b6_review))


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

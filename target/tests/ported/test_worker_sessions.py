"""Ported from SOURCE M7 `tests/test_worker_sessions.py`: the 19 tests over the session lifecycle
(WorkerSessions), the archive store and export/restore that need no provider, executor, container
entry, CLI, observer (the observed-transition test needs the S9 Observer) or monitoring (those stay with RunTask/claude_cli in S4, S9 and S10).

Unchanged test bodies. Adaptations, named: imports point at the target; `SessionArchives` receives its
store (the target injects the restricted `FileArtifacts` of the archive root instead of constructing it
from a path), so the file-local `SessionArchives(path)` below wraps exactly that; `IMAGE` comes from
the ported isolated-worker suite as in M7.
"""

import base64
import copy
import json
from pathlib import Path

import pytest
from test_isolated_worker import IMAGE

from codex_harness.execution.adapters import worker_sessions as session_adapter
from codex_harness.execution.adapters.worker_sessions import (
    export_session,
    read_export,
    restore_session,
)
from codex_harness.execution.application.worker_sessions import BUCKET, WorkerSessions
from codex_harness.execution.domain import worker_sessions as ws
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

CANARY = "CANARY-7e1d9c3b5a2f4e6d8c0b1a2f3e4d5c6b"


def SessionArchives(root):  # noqa: N802 - the M7 constructor form, adapted (see the module docstring)
    return session_adapter.SessionArchives(FileArtifacts(str(root)))


MODEL = "claude-stub-session"

def identity(**changes):
    body = {"task_id": "task-1", "repository": "zeus", "workspace": "w" * 16, "provider": "claude",
            "model": MODEL, "runtime_image": IMAGE, "runtime_digest": "r" * 16, "policy_digest": "p" * 16,
            "config_digest": "c" * 16}
    return {**body, **changes}

def owner(execution="exec-a", generation=1, attempt=1):
    return {"execution": execution, "generation": generation, "attempt": attempt}

def candidate(n):
    return {"revision": format(n, "x").rjust(40, "a"), "tree": format(n, "x").rjust(40, "b"),
            "base": "c" * 40}

def decide(store, decision_id, frozen, *, accepted, phase="review_lead", status="succeeded",
           execution_ref="sha256:" + "e" * 64):
    with store.transaction() as tx:
        tx.put("decisions_pending", decision_id, {
            "id": decision_id, "phase": phase, "status": status, "actor": "lead:improvement",
            "input": {"candidate": frozen},
            "result": {"accepted": accepted, "execution_ref": execution_ref, "reason": "fixture"}})

def evidence_store(root):
    """A real verified evidence store (FileArtifacts); everything put into it is labelled fixture text."""
    return FileArtifacts(str(root / "evidence"))

def accept_for_promotion(store, owner_sessions, root, n, evidence):
    """Adopt one turn, freeze candidate n, and record a succeeded conductor acceptance whose own
    execution receipt exists in `evidence`. Returns (row, promoted evidence ref)."""
    review_ref = evidence.put(json.dumps({"fixture": "review execution receipt", "n": n}), "fixture")["ref"]
    plan = owner_sessions.begin("task-1", identity(), owner())
    adopt_turn(owner_sessions, root, "t1", plan["session_id"], "/workspace", [b"a"], owner())
    frozen = candidate(n)
    owner_sessions.submit("task-1", frozen)
    decide(store, f"review-{n}", frozen, accepted=True, phase="review_conductor", execution_ref=review_ref)
    row = owner_sessions.record_review("task-1", f"review-{n}")
    assert row["state"] == ws.ACCEPTED
    promoted = evidence.put(json.dumps({"fixture": "promoted accepted evidence", "n": n}), "fixture")["ref"]
    return row, promoted

def write_session(home, cwd, sid, lines, extra=None):
    """A fixture CLI home: the exact transcript plus optional files under the session directory."""
    base = Path(home) / "projects" / ws.project_key(cwd)
    base.mkdir(parents=True, exist_ok=True)
    (base / (sid + ".jsonl")).write_bytes(b"".join(line + b"\n" for line in lines))
    for relative, data in (extra or {}).items():
        target = base / sid / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return base

def sessions(tmp_path, store=None, **kwargs):
    store = store or MemoryStore()
    return store, WorkerSessions(store, SessionArchives(tmp_path / "archives"), **kwargs)

def adopt_turn(owner_sessions, tmp_path, name, sid, cwd, lines, who, usage=None):
    home, export = tmp_path / (name + "-home"), tmp_path / (name + "-export")
    write_session(home, cwd, sid, lines)
    export_session(home, cwd, sid, export)
    return owner_sessions.checkpoint("task-1", who, export, usage=usage)

@pytest.mark.parametrize("field", ["task_id", "repository", "workspace"])
def test_foreign_task_repository_or_workspace_is_refused_without_change(tmp_path, field):
    _, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner())
    adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner())
    before = owner_sessions.status("task-1")
    changed = identity(**{field: "other"})
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        owner_sessions.begin("task-1", changed, owner("exec-b"))
    assert refused.value.reason in ({"session_foreign", "identity_malformed"})
    assert owner_sessions.status("task-1") == before

@pytest.mark.parametrize("field", ["model", "policy_digest", "config_digest", "runtime_image", "runtime_digest"])
def test_model_or_policy_mismatch_refuses_native_resume_and_requires_fresh_handoff(tmp_path, field):
    _, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner())
    adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner())
    with pytest.raises(ws.WorkerSessionRefused, match="fresh evidence handoff") as refused:
        owner_sessions.begin("task-1", identity(**{field: "changed"}), owner("exec-b"))
    assert refused.value.reason == "session_incompatible"
    status = owner_sessions.status("task-1")["sessions"][0]
    assert status["state"] == ws.INCOMPATIBLE and status["owner"] is None
    assert status["reason"] == "fresh_evidence_handoff_required"
    with pytest.raises(ws.WorkerSessionRefused):  # never quietly resumed afterwards either
        owner_sessions.begin("task-1", identity(), owner("exec-c"))

def test_corrupt_or_missing_archive_is_an_explicit_state(tmp_path):
    for damage, state in (("corrupt", ws.ARCHIVE_CORRUPT), ("missing", ws.ARCHIVE_MISSING)):
        root = tmp_path / damage
        _, owner_sessions = sessions(root)
        plan = owner_sessions.begin("task-1", identity(), owner())
        row = adopt_turn(owner_sessions, root, "t1", plan["session_id"], "/workspace", [b"a"], owner())
        stored = owner_sessions.archives.root / (row["checkpoints"][-1]["archive"]["ref"][7:] + ".txt")
        if damage == "corrupt":
            stored.write_bytes(stored.read_bytes().replace(b'"schema"', b'"schemb"'))
        else:
            stored.unlink()
        with pytest.raises(ws.WorkerSessionRefused):
            owner_sessions.begin("task-1", identity(), owner("exec-b"))
        assert owner_sessions.status("task-1")["sessions"][0]["state"] == state

def test_archive_with_valid_hash_but_altered_file_bytes_is_corrupt(tmp_path):
    archives = SessionArchives(tmp_path / "archives")
    home, export = tmp_path / "home", tmp_path / "export"
    sid = "33333333-3333-4333-8333-333333333333"
    write_session(home, "/workspace", sid, [b"a"])
    export_session(home, "/workspace", sid, export)
    receipt = archives.put(read_export(export, session_id=sid))
    document = json.loads(archives.store._body(receipt["ref"]))
    path = next(iter(document["files"]))
    document["files"][path] = base64.b64encode(b"forged").decode()
    forged = archives.store.put(json.dumps(document, sort_keys=True, separators=(",", ":")), "fixture")
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        archives.load(forged["ref"], session_id=sid)
    assert refused.value.reason == "archive_corrupt"
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        archives.load(receipt["ref"], session_id="44444444-4444-4444-8444-444444444444")
    assert refused.value.reason == "archive_foreign_session"

@pytest.mark.parametrize("relative", ["../escape.jsonl", "projects/-workspace/other.jsonl",
                                      "projects/-workspace/SID/.credentials.json", "settings.json",
                                      "projects/-workspace/SID/a\\b", "C:/x", "/abs",
                                      "projects/-workspace/SID/CON.txt", "projects/-other/SID.jsonl"])
def test_manifest_refuses_escape_foreign_and_secret_paths(relative):
    sid = "55555555-5555-4555-8555-555555555555"
    files = [{"path": f"projects/-workspace/{sid}.jsonl", "bytes": 1, "sha256": "0" * 64},
             {"path": relative.replace("SID", sid), "bytes": 1, "sha256": "0" * 64}]
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        ws.validate_manifest({"schema": ws.ARCHIVE_SCHEMA, "session_id": sid, "project": "-workspace", "files": files})
    assert refused.value.reason == "archive_path_refused"

def test_restore_verifies_the_named_manifest_and_never_overwrites(tmp_path):
    sid = "77777777-7777-4777-8777-777777777777"
    write_session(tmp_path / "home", "/workspace", sid, [b"a"])
    manifest = export_session(tmp_path / "home", "/workspace", sid, tmp_path / "staged")
    named = {k: manifest[k] for k in ("schema", "session_id", "project", "files")}
    other = {**named, "files": [{**named["files"][0], "sha256": "f" * 64}]}
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        restore_session(tmp_path / "staged", tmp_path / "fresh", session_id=sid, expected_manifest=other)
    assert refused.value.reason == "archive_manifest_mismatch" and not (tmp_path / "fresh").exists()
    write_session(tmp_path / "occupied", "/workspace", sid, [b"different"])
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        restore_session(tmp_path / "staged", tmp_path / "occupied", session_id=sid, expected_manifest=named)
    assert refused.value.reason == "archive_restore_conflict"
    restore_session(tmp_path / "staged", tmp_path / "fresh", session_id=sid, expected_manifest=named)
    assert (tmp_path / "fresh" / named["files"][0]["path"]).read_bytes() == b"a\n"

def test_windows_and_posix_workspace_keys_and_path_forms():
    assert ws.project_key("/workspace") == "-workspace"
    assert ws.project_key("C:\\work\\zeus repo") == "C--work-zeus-repo"
    assert ws.project_key("/home/w/작업") == "-home-w---"
    sid = "88888888-8888-4888-8888-888888888888"
    assert ws.allowed_path(f"projects/C--work/{sid}.jsonl", "C--work", sid)
    for bad in (f"projects\\C--work\\{sid}.jsonl", f"C:/projects/C--work/{sid}.jsonl",
                f"projects/C--work/{sid}/aux.txt", f"projects/C--work/{sid}/x."):
        assert not ws.allowed_path(bad, "C--work", sid)

def test_two_owners_race_for_one_logical_session(tmp_path):
    _, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner("exec-a"))
    assert owner_sessions.begin("task-1", identity(), owner("exec-a")) == plan  # duplicate begin
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        owner_sessions.begin("task-1", identity(), owner("exec-b"))
    assert refused.value.reason == "session_owned"
    adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner("exec-a"))
    # B wins the claim while A is verifying the archive outside the transaction: A must lose cleanly.
    load, raced = owner_sessions.archives.load, []

    def verifying(reference, *, session_id):
        if not raced:  # a controlled barrier: B runs to completion inside A's verification window
            raced.append(None)
            raced[0] = owner_sessions.begin("task-1", identity(), owner("exec-b"))
        return load(reference, session_id=session_id)
    owner_sessions.archives.load = verifying
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        owner_sessions.begin("task-1", identity(), owner("exec-a", 1, 2))
    assert refused.value.reason == "session_owned" and raced[0]["mode"] == ws.MODE_RESUME
    assert owner_sessions.status("task-1")["sessions"][0]["owner"] == owner("exec-b")

@pytest.mark.parametrize("field", ["model", "policy_digest", "runtime_image", "config_digest", "runtime_digest"])
def test_duplicate_begin_by_the_owner_checks_compatibility_first_and_preserves_the_claim(tmp_path, field):
    """Owner synthetic reproduction: same owner + changed model used to get a plan back."""
    store, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner("exec-a"))
    assert owner_sessions.begin("task-1", identity(), owner("exec-a")) == plan  # exact duplicate succeeds
    before = copy.deepcopy(store.data)
    for who in (owner("exec-a"), owner("exec-b")):
        with pytest.raises(ws.WorkerSessionRefused) as refused:
            owner_sessions.begin("task-1", identity(**{field: "changed"}), who)
        assert refused.value.reason == "session_incompatible"
    assert store.data == before  # the valid owner's claim and row are untouched
    # The valid owner's turn and archive are unaffected; its resumed claim is guarded the same way.
    row = adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner("exec-a"))
    frozen = candidate(14)
    owner_sessions.submit("task-1", frozen)
    decide(store, "review-14", frozen, accepted=False)
    owner_sessions.record_review("task-1", "review-14")
    resumed = owner_sessions.begin("task-1", identity(), owner("exec-b", 2, 1))
    assert resumed["mode"] == ws.MODE_RESUME and owner_sessions.begin("task-1", identity(), owner("exec-b", 2, 1)) == resumed
    before = copy.deepcopy(store.data)
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        owner_sessions.begin("task-1", identity(**{field: "changed"}), owner("exec-b", 2, 1))
    assert refused.value.reason == "session_incompatible" and store.data == before
    reference = row["checkpoints"][-1]["archive"]["ref"]
    assert owner_sessions.archives.load(reference, session_id=plan["session_id"])["files"]

def test_duplicate_checkpoint_and_review_events_are_idempotent(tmp_path):
    store, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner())
    home = tmp_path / "home"
    write_session(home, "/workspace", plan["session_id"], [b"a"])
    export_session(home, "/workspace", plan["session_id"], tmp_path / "export")
    first = owner_sessions.checkpoint("task-1", owner(), tmp_path / "export", usage=None)
    again = owner_sessions.checkpoint("task-1", owner(), tmp_path / "export", usage=None)
    assert again == first and len(again["checkpoints"]) == 1
    frozen = candidate(2)
    submitted = owner_sessions.submit("task-1", frozen)
    assert owner_sessions.submit("task-1", frozen) == submitted
    decide(store, "review-lead", frozen, accepted=True)
    decide(store, "review-conductor", frozen, accepted=True, phase="review_conductor")
    assert owner_sessions.record_review("task-1", "review-lead")["state"] == ws.AWAITING_REVIEW
    accepted = owner_sessions.record_review("task-1", "review-conductor")
    assert accepted["state"] == ws.ACCEPTED
    assert owner_sessions.record_review("task-1", "review-conductor") == accepted
    assert [r["outcome"] for r in accepted["reviews"]] == ["lead_accepted", "accepted"]

def test_crash_after_archive_write_before_store_commit_replays_once(tmp_path):
    _, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner())
    write_session(tmp_path / "home", "/workspace", plan["session_id"], [b"a"])
    export_session(tmp_path / "home", "/workspace", plan["session_id"], tmp_path / "export")
    commit, crashed = owner_sessions._commit, []

    def crash(task_id, version, change):  # INJECTED: the process dies after the archive write
        if not crashed:
            crashed.append(1)
            raise RuntimeError("injected crash before the store commit")
        return commit(task_id, version, change)
    owner_sessions._commit = crash
    with pytest.raises(RuntimeError):
        owner_sessions.checkpoint("task-1", owner(), tmp_path / "export", usage=None)
    stored = sorted(p.name for p in owner_sessions.archives.root.glob("*.txt"))
    assert len(stored) == 1 and owner_sessions.status("task-1")["sessions"][0]["state"] == ws.ACTIVE
    row = owner_sessions.checkpoint("task-1", owner(), tmp_path / "export", usage=None)
    assert row["state"] == ws.CHECKPOINTED and len(row["checkpoints"]) == 1
    assert sorted(p.name for p in owner_sessions.archives.root.glob("*.txt")) == stored

def test_unproven_resume_continuity_is_unresolved_not_relabelled(tmp_path):
    store, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner())
    adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a", b"b"], owner())
    frozen = candidate(3)
    owner_sessions.submit("task-1", frozen)
    decide(store, "review-3", frozen, accepted=False)
    owner_sessions.record_review("task-1", "review-3")
    owner_sessions.begin("task-1", identity(), owner("exec-b"))
    with pytest.raises(ws.WorkerSessionRefused) as refused:  # a fresh context, not the archived one
        adopt_turn(owner_sessions, tmp_path, "t2", plan["session_id"], "/workspace", [b"new"], owner("exec-b"))
    assert refused.value.reason == "resume_continuity_unproven"
    status = owner_sessions.status("task-1")["sessions"][0]
    assert status["state"] == ws.UNRESOLVED and status["owner"] is None and status["checkpoints"] == 1
    # Explicit reconcile from retained bytes that DO continue the archive.
    write_session(tmp_path / "t3-home", "/workspace", plan["session_id"], [b"a", b"b", b"c"])
    export_session(tmp_path / "t3-home", "/workspace", plan["session_id"], tmp_path / "t3-export")
    row = owner_sessions.reconcile("task-1", tmp_path / "t3-export")
    assert row["state"] == ws.CHECKPOINTED and row["checkpoints"][-1]["continuity"] == "prefix_verified"

def test_failed_turn_releases_to_the_prior_resume_point(tmp_path):
    store, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner())
    row = adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner())
    frozen = candidate(4)
    owner_sessions.submit("task-1", frozen)
    decide(store, "review-4", frozen, accepted=False)
    owner_sessions.record_review("task-1", "review-4")
    owner_sessions.begin("task-1", identity(), owner("exec-b"))
    released = owner_sessions.release("task-1", owner("exec-b"), "turn_failed")
    assert released["state"] == ws.CORRECTION_READY and released["owner"] is None
    assert released["checkpoints"] == row["checkpoints"]
    with pytest.raises(ws.WorkerSessionRefused):
        owner_sessions.release("task-1", owner("exec-z"), "not mine")

def test_review_wait_holds_no_owner_and_makes_no_calls(tmp_path):
    store, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner())
    adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner())
    owner_sessions.submit("task-1", candidate(5))
    before = {bucket for (bucket, _key) in store.data}
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        owner_sessions.begin("task-1", identity(), owner("exec-b"))
    assert refused.value.reason == "session_not_resumable"
    status = owner_sessions.status("task-1")["sessions"][0]
    assert status["state"] == ws.AWAITING_REVIEW and status["owner"] is None
    assert "no model calls" in status["next_action"]
    assert {bucket for (bucket, _key) in store.data} == before == {BUCKET}  # no reservation, no invocation
    for bad in ({"phase": "diagnose"}, {"status": "running"}, {"candidate": candidate(6)}):
        decide(store, "bad", bad.get("candidate", candidate(5)), accepted=False,
               phase=bad.get("phase", "review_lead"), status=bad.get("status", "succeeded"))
        with pytest.raises(ws.WorkerSessionRefused):
            owner_sessions.record_review("task-1", "bad")
    with pytest.raises(ws.WorkerSessionRefused):
        owner_sessions.record_review("task-1", "no-such-decision")
    assert owner_sessions.status("task-1")["sessions"][0]["state"] == ws.AWAITING_REVIEW

def test_rejected_candidate_is_immutable(tmp_path):
    store, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner())
    adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner())
    frozen = candidate(7)
    owner_sessions.submit("task-1", frozen)
    decide(store, "review-7", frozen, accepted=False)
    rejected = owner_sessions.record_review("task-1", "review-7")["candidates"][0]
    owner_sessions.begin("task-1", identity(), owner("exec-b"))
    adopt_turn(owner_sessions, tmp_path, "t2", plan["session_id"], "/workspace", [b"a", b"b"], owner("exec-b"))
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        owner_sessions.submit("task-1", frozen)
    assert refused.value.reason == "candidate_rejected_immutable"
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        owner_sessions.submit("task-1", {**frozen, "tree": "d" * 40})
    assert refused.value.reason == "candidate_conflict"
    row = owner_sessions.submit("task-1", candidate(8))
    assert row["candidates"][0] == rejected and row["state"] == ws.AWAITING_REVIEW

def test_closed_only_after_promotion_and_cleanup_failure_retains_bytes(tmp_path):
    evidence = evidence_store(tmp_path)
    store, owner_sessions = sessions(tmp_path, evidence=evidence)
    plan = owner_sessions.begin("task-1", identity(), owner())
    row = adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner())
    reference = row["checkpoints"][-1]["archive"]["ref"]
    frozen = candidate(9)
    owner_sessions.submit("task-1", frozen)
    for step in (lambda: owner_sessions.close("task-1"), lambda: owner_sessions.promote("task-1", "sha256:" + "1" * 64)):
        with pytest.raises(ws.WorkerSessionRefused):
            step()
    review_ref = evidence.put(json.dumps({"fixture": "review execution receipt"}), "fixture")["ref"]
    decide(store, "review-9", frozen, accepted=True, phase="review_conductor", execution_ref=review_ref)
    accepted = owner_sessions.record_review("task-1", "review-9")
    with pytest.raises(ws.WorkerSessionRefused):
        owner_sessions.close("task-1")  # accepted but not promoted
    promoted = evidence.put(json.dumps({"fixture": "promoted accepted evidence"}), "fixture")["ref"]
    receipt = evidence.put(json.dumps(ws.promotion_receipt(accepted, [promoted])), "fixture")["ref"]
    owner_sessions.promote("task-1", receipt)

    def failing(_row):
        raise PermissionError("injected cleanup failure")
    kept = owner_sessions.close("task-1", cleanup=failing)
    assert kept["state"] == ws.ARCHIVAL_PENDING and kept["cleanup"]["state"] == "failed"
    assert kept["cleanup"]["error_type"] == "PermissionError" and kept["cleanup"]["archive_retained"] == reference
    view = owner_sessions.status("task-1")["sessions"][0]
    assert view["blocked"] and view["next_owner"] == "operator" and "archive is retained" in view["next_action"]
    assert owner_sessions.archives.load(reference, session_id=plan["session_id"])["files"]
    closed = owner_sessions.close("task-1", cleanup=lambda _row: None)
    assert closed["state"] == ws.CLOSED and owner_sessions.archives.load(reference, session_id=plan["session_id"])
    assert owner_sessions.close("task-1") == closed

def test_promotion_and_closure_require_a_verified_receipt_bound_to_this_session(tmp_path):
    """The owner's synthetic reproduction (adopt/freeze/accept, promote(task, sha256:000..0), close)
    and every receipt that is not bound to this session's accepted candidate/archive/review."""
    # 1. No configured evidence source: refused, state unchanged (was: archival_pending then closed).
    store, owner_sessions = sessions(tmp_path / "unconfigured")
    evidence = evidence_store(tmp_path / "unconfigured")
    accept_for_promotion(store, owner_sessions, tmp_path / "unconfigured", 20, evidence)
    before = copy.deepcopy(store.data)
    for step in (lambda: owner_sessions.promote("task-1", "sha256:" + "0" * 64), lambda: owner_sessions.close("task-1")):
        with pytest.raises(ws.WorkerSessionRefused) as refused:
            step()
        assert refused.value.reason in ("promotion_evidence_unconfigured", "session_not_promoted")
    assert store.data == before

    # 2. Configured store: missing, unrelated, malformed and incompletely backed receipts all refuse.
    root = tmp_path / "configured"
    evidence = evidence_store(root)
    store, owner_sessions = sessions(root, evidence=evidence)
    accepted, promoted = accept_for_promotion(store, owner_sessions, root, 21, evidence)
    archive_ref = accepted["checkpoints"][-1]["archive"]["ref"]
    good = ws.promotion_receipt(accepted, [promoted])
    other_session = {**good, "session_id": "ffffffff-ffff-4fff-8fff-ffffffffffff"}
    cases = {
        "promotion_receipt_missing": "sha256:" + "0" * 64,
        "promotion_receipt_malformed": evidence.put("promoted evidence", "fixture")["ref"],  # any artifact
        "promotion_receipt_unrelated": evidence.put(json.dumps(other_session), "fixture")["ref"],
    }
    for key, value in (("candidate", {**good["candidate"], "tree": "d" * 40}),
                       ("archive", {**good["archive"], "ref": "sha256:" + "1" * 64}),
                       ("review", {**good["review"], "decision_id": "another-review"}),
                       ("task_id", "task-2")):
        cases.setdefault("promotion_receipt_unrelated:" + key,
                         evidence.put(json.dumps({**good, key: value}), "fixture")["ref"])
    cases["promotion_receipt_malformed:extra"] = evidence.put(json.dumps({**good, "approved": True}), "fixture")["ref"]
    cases["promotion_receipt_malformed:empty"] = evidence.put(json.dumps({**good, "evidence": []}), "fixture")["ref"]
    cases["promotion_evidence_missing"] = evidence.put(json.dumps(
        ws.promotion_receipt(accepted, ["sha256:" + "9" * 64])), "fixture")["ref"]
    before = copy.deepcopy(store.data)
    for expected, reference in cases.items():
        with pytest.raises(ws.WorkerSessionRefused) as refused:
            owner_sessions.promote("task-1", reference)
        assert refused.value.reason == expected.split(":")[0], expected
    assert store.data == before  # nothing moved: still accepted, no promotion record
    # A modified receipt file is corrupt, never trusted by its name.
    receipt = evidence.put(json.dumps(good), "fixture")["ref"]
    stored = evidence.root / (receipt[7:] + ".txt")
    original = stored.read_bytes()
    stored.write_bytes(original.replace(b"task-1", b"task-X"))
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        owner_sessions.promote("task-1", receipt)
    assert refused.value.reason == "promotion_receipt_malformed" and store.data == before
    stored.write_bytes(original)

    # 3. The bound receipt promotes; closure re-verifies it, and default close retains the archive.
    row = owner_sessions.promote("task-1", receipt)
    assert row["state"] == ws.ARCHIVAL_PENDING and row["promotion"]["verified"] is True
    assert row["promotion"]["evidence"] == [promoted] and row["promotion"]["archive_ref"] == archive_ref
    assert owner_sessions.promote("task-1", receipt) == row  # duplicate promotion event
    stored.unlink()  # the receipt disappears between promotion and closure
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        owner_sessions.close("task-1")
    assert refused.value.reason == "promotion_receipt_missing"
    assert owner_sessions.status("task-1")["sessions"][0]["state"] == ws.ARCHIVAL_PENDING
    evidence.put(json.dumps(good), "fixture")
    unconfigured = WorkerSessions(store, owner_sessions.archives)  # the same row, no evidence source
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        unconfigured.close("task-1")
    assert refused.value.reason == "promotion_evidence_unconfigured"
    closed = owner_sessions.close("task-1")
    assert closed["state"] == ws.CLOSED and closed["cleanup"] == {
        "state": "not_requested", "at": closed["cleanup"]["at"], "archive_retained": archive_ref}
    assert owner_sessions.archives.load(archive_ref, session_id=closed["session_id"])["files"]


def test_cumulative_usage_is_never_double_counted():
    sid, other = "99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    raw = {"input_tokens": 300, "output_tokens": 30}
    baseline = {"session_id": sid, "raw": {"input_tokens": 100, "output_tokens": 10}}
    assert ws.usage_delta(mode=ws.MODE_RESUME, session_id=sid, baseline=baseline, raw=raw)["delta"] == \
        {"input_tokens": 200, "output_tokens": 20}
    for base in (None, {**baseline, "session_id": other}, {"session_id": sid, "raw": {"input_tokens": 400,
                                                                                      "output_tokens": 10}}):
        unknown = ws.usage_delta(mode=ws.MODE_RESUME, session_id=sid, baseline=base, raw=raw)
        assert unknown["delta"] is None and unknown["basis"].startswith("unknown") and unknown["raw"] == raw
    assert ws.usage_delta(mode=ws.MODE_FRESH, session_id=sid, baseline=None, raw=raw)["delta"] == raw
    assert ws.usage_delta(mode=ws.MODE_FRESH, session_id=sid, baseline=None, raw=None)["basis"] == "unknown"

def test_state_matrix_refuses_every_undeclared_transition():
    for current, allowed in ws.TRANSITIONS.items():
        for target in ws.STATES:
            if target in allowed:
                assert ws.transition(current, target) == target
            else:
                with pytest.raises(ws.WorkerSessionRefused):
                    ws.transition(current, target)
    assert ws.TRANSITIONS[ws.CLOSED] == frozenset() and ws.CLOSED in ws.TRANSITIONS[ws.ARCHIVAL_PENDING]

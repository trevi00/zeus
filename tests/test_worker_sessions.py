"""INV-WORKER-SESSION-001: durable Claude task sessions, against the fixed acceptance matrix.

Real temporary files and a real MemoryStore throughout. Provider turns run `claude_protocol_child.py`
(scenario `session`), a LABELLED fixture that imitates the CLI's transcript store; it is not the real
transcript format and proves nothing about a model. The isolated test uses the injected FakeDocker of
test_isolated_worker plus the REAL entry `serve` and REAL `ClaudeCodeRuntime` inside the fake
container process. No model, provider, Docker daemon or production store is touched. The real
two-turn/container-recreation probe is owner work (`ZEUS_REAL_CLAUDE_SESSION_PROBE`, skipped here).
"""
import base64
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_isolated_worker import IMAGE, TOKEN, FakeDocker, git

from codex_harness.adapters import isolated_worker as iw
from codex_harness.adapters import isolated_worker_entry as entry
from codex_harness.adapters.claude_cli import ClaudeCodeRuntime, ClaudeUnavailable, claude_settings
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.store import MemoryStore
from codex_harness.adapters.worker_sessions import (
    EXPORT_DIRECTORY,
    MANIFEST,
    RESTORE_DIRECTORY,
    SessionArchives,
    export_session,
    read_export,
    restore_session,
)
from codex_harness.application.worker_sessions import BUCKET, WorkerSessions
from codex_harness.domain import worker_sessions as ws
from codex_harness.domain.model import ContractError

CHILD = Path(__file__).resolve().parent / "claude_protocol_child.py"
CANARY = "CANARY-7e1d9c3b5a2f4e6d8c0b1a2f3e4d5c6b"
RUNTIME = {"output_format": "stream-json", "input_format": "text", "verbose": True,
           "permission_mode": "acceptEdits", "permission_prompts": "none", "setting_sources": "",
           "strict_mcp_config": True, "tools": ["Bash", "Read", "Edit"],
           "allowed_tools": ["Read", "Edit"], "disallowed_tools": ["Task"]}
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"summary": {"type": "string"}, "tests": {"type": "array", "items": {"type": "string"}}},
          "required": ["summary", "tests"]}
MODEL = "claude-stub-session"
REAL_TREE = iw.ProcessTree


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


def decide(store, decision_id, frozen, *, accepted, phase="review_lead", status="succeeded"):
    with store.transaction() as tx:
        tx.put("decisions_pending", decision_id, {
            "id": decision_id, "phase": phase, "status": status, "actor": "lead:improvement",
            "input": {"candidate": frozen},
            "result": {"accepted": accepted, "execution_ref": "sha256:" + "e" * 64, "reason": "fixture"}})


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


def sessions(tmp_path, store=None):
    store = store or MemoryStore()
    return store, WorkerSessions(store, SessionArchives(tmp_path / "archives"))


def adopt_turn(owner_sessions, tmp_path, name, sid, cwd, lines, who, usage=None):
    home, export = tmp_path / (name + "-home"), tmp_path / (name + "-export")
    write_session(home, cwd, sid, lines)
    export_session(home, cwd, sid, export)
    return owner_sessions.checkpoint("task-1", who, export, usage=usage)


def cli(session_home, **kwargs):
    return ClaudeCodeRuntime(model=MODEL, runtime=RUNTIME, executable=str(CHILD), launcher=[sys.executable],
                             max_budget_usd=1.0, settings_document=claude_settings(RUNTIME),
                             session_home=str(session_home), **kwargs)


# ---- default fresh behaviour is unchanged -----------------------------------------------------------
def test_default_fresh_command_and_result_are_unchanged(tmp_path):
    runtime = ClaudeCodeRuntime(model=MODEL, runtime=RUNTIME, executable=str(CHILD), launcher=[sys.executable],
                                max_budget_usd=1.0)
    argv, _ = runtime._command(schema=SCHEMA, session_id="0" * 8 + "-0000-4000-8000-" + "0" * 12)
    assert "--session-id" in argv and "--resume" not in argv and "--continue" not in argv
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with ClaudeCodeRuntime(model="claude-stub-normal", runtime=RUNTIME, executable=str(CHILD),
                           launcher=[sys.executable], max_budget_usd=1.0) as opened:
        result = opened.run("prompt", str(workspace), SCHEMA, timeout=60)
    assert result["session"]["resume"] == "unsupported" and "task_session" not in result
    assert "--resume" not in json.dumps(result["command"]["argv"]) and result["answer"] is not None
    assert iw.request_protocol(False, False) == iw.PROTOCOL and iw.request_protocol(True, False) == iw.DELIVERY_PROTOCOL


def test_executor_default_path_and_unsupported_combinations_refuse_before_entry():
    assignment = SimpleNamespace(transport="claude_cli")
    lease = {"id": "exec-a", "generation": 2, "attempt": 1}
    host = SimpleNamespace(worker_sessions=object(), isolation=None)
    isolated = SimpleNamespace(worker_sessions=object(), isolation=SimpleNamespace(config={"image": IMAGE}))
    binding = {"task_id": "task-1", "repository": "zeus"}
    assert Executor._task_session_owner(host, None, assignment, False, lease, 4) is None  # legacy path
    for this, args, message in (
            (SimpleNamespace(worker_sessions=None, isolation=None), (binding, assignment, False, lease, 1), "not configured"),
            (host, (binding, assignment, False, lease, 1), "isolated Claude worker"),
            (isolated, (binding, SimpleNamespace(transport="app_server"), False, lease, 1), "isolated Claude worker"),
            (isolated, (binding, assignment, True, lease, 1), "review never"),
            (isolated, (binding, assignment, False, None, 1), "leased execution"),
            (isolated, (binding, assignment, False, lease, 4), "one provider call"),
            (isolated, ({"task_id": "task-1"}, assignment, False, lease, 1), "exactly task_id")):
        with pytest.raises(ContractError, match=message):
            Executor._task_session_owner(this, *args)
    assert Executor._task_session_owner(isolated, binding, assignment, False, lease, 1) == owner("exec-a", 2, 1)


# ---- native resume uses the exact archive and id; history is retained --------------------------------
def test_two_turn_resume_restores_exact_archive_and_retains_history(tmp_path):
    store, owner_sessions = sessions(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = owner_sessions.begin("task-1", identity(), owner("exec-a"))
    assert plan["mode"] == ws.MODE_FRESH and plan["archive"] is None
    first_home = tmp_path / "container-1" / ".claude"
    with cli(first_home) as opened:
        first = opened.run("turn one", str(workspace), SCHEMA, timeout=60, session_id=plan["session_id"],
                           task_session={"mode": ws.MODE_FRESH, "session_id": plan["session_id"],
                                         "export": str(tmp_path / "export-1")})
    assert first["answer"]["tests"] == ["turn 1", "fresh"] and first["task_session"]["exported"]
    assert "--session-id" in first["command"]["argv"] and "--resume" not in first["command"]["argv"]
    usage_one = ws.usage_delta(mode=ws.MODE_FRESH, session_id=plan["session_id"], baseline=None, raw=first["usage"])
    row = owner_sessions.checkpoint("task-1", owner("exec-a"), tmp_path / "export-1", usage=usage_one)
    assert row["state"] == ws.CHECKPOINTED and row["owner"] is None
    assert row["checkpoints"][-1]["continuity"] == "fresh_session"
    frozen = candidate(1)
    owner_sessions.submit("task-1", frozen)
    decide(store, "review-1", frozen, accepted=False)
    assert owner_sessions.record_review("task-1", "review-1")["state"] == ws.CORRECTION_READY

    # Container recreation: a new owner, a new empty home; only the verified archive carries context.
    resumed = owner_sessions.begin("task-1", identity(), owner("exec-b", 2, 1))
    assert resumed["mode"] == ws.MODE_RESUME and resumed["session_id"] == plan["session_id"]
    assert resumed["archive"]["ref"] == row["checkpoints"][-1]["archive"]["ref"]
    restore = tmp_path / "restore-2"
    manifest = owner_sessions.stage(resumed, restore)
    second_home = tmp_path / "container-2" / ".claude"
    with cli(second_home) as opened:
        second = opened.run("turn two", str(workspace), SCHEMA, timeout=60, session_id=resumed["session_id"],
                            task_session={"mode": ws.MODE_RESUME, "session_id": resumed["session_id"],
                                          "restore": str(restore), "manifest": manifest,
                                          "export": str(tmp_path / "export-2")})
    argv = second["command"]["argv"]
    assert argv[argv.index("--resume") + 1] == plan["session_id"] and "--session-id" not in argv
    assert "--continue" not in argv and second["session"]["resume"] == "native"
    assert second["answer"]["tests"] == ["turn 2", "resumed"] and second["session"]["match"]
    usage_two = ws.usage_delta(mode=ws.MODE_RESUME, session_id=resumed["session_id"],
                               baseline=resumed["usage_baseline"], raw=second["usage"])
    assert usage_two["delta"] == {"input_tokens": 100, "output_tokens": 10, "cache_creation_input_tokens": 0,
                                  "cache_read_input_tokens": 5}  # cumulative 200/20 minus baseline 100/10
    row = owner_sessions.checkpoint("task-1", owner("exec-b", 2, 1), tmp_path / "export-2", usage=usage_two)
    assert row["state"] == ws.CHECKPOINTED and row["checkpoints"][-1]["continuity"] == "prefix_verified"
    assert len(row["checkpoints"]) == 2 and [r["outcome"] for r in row["reviews"]] == ["rejected"]
    assert row["candidates"][0]["outcome"] == "rejected" and row["candidates"][0]["revision"] == frozen["revision"]
    # Secret-file exclusion on the real exported bytes: decoys existed in the home but never left it.
    exported = read_export(tmp_path / "export-2", session_id=plan["session_id"])
    assert (second_home / ".credentials.json").exists() and (second_home / "settings.json").exists()
    assert all(CANARY.encode() not in data for data in exported["files"].values())
    assert sorted(p.rsplit("/", 1)[-1] for p in exported["files"]) == [plan["session_id"] + ".jsonl",
                                                                       "turn-1.txt", "turn-2.txt"]
    assert second["task_session"]["excluded"] == 1  # the session directory's dot-file


def test_resume_without_restorable_archive_or_capability_refuses_before_the_process(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sid = "11111111-1111-4111-8111-111111111111"
    for task_session in ({"mode": ws.MODE_RESUME, "session_id": sid, "restore": str(tmp_path / "none"),
                          "manifest": {}, "export": str(tmp_path / "e")},
                         {"mode": "latest", "session_id": sid, "export": str(tmp_path / "e")},
                         {"mode": ws.MODE_FRESH, "session_id": "22222222-2222-4222-8222-222222222222",
                          "export": str(tmp_path / "e")}):
        with cli(tmp_path / "home") as opened, pytest.raises(ContractError):
            opened.run("p", str(workspace), SCHEMA, timeout=30, session_id=sid, task_session=task_session)
        assert opened.process is None and not (workspace / "stub-runs.log").exists()
    no_home = ClaudeCodeRuntime(model=MODEL, runtime=RUNTIME, executable=str(CHILD), launcher=[sys.executable],
                                max_budget_usd=1.0)
    with no_home as opened, pytest.raises(ContractError, match="owned CLI home"):
        opened.run("p", str(workspace), SCHEMA, timeout=30, session_id=sid,
                   task_session={"mode": ws.MODE_FRESH, "session_id": sid, "export": str(tmp_path / "e")})
    runtime = cli(tmp_path / "home")
    with runtime as opened:
        opened.capabilities = tuple(flag for flag in opened.capabilities if flag != "--resume")
        with pytest.raises(ClaudeUnavailable, match="--resume"):
            opened.run("p", str(workspace), SCHEMA, timeout=30, session_id=sid,
                       task_session={"mode": ws.MODE_RESUME, "session_id": sid, "export": str(tmp_path / "e")})
    assert not (workspace / "stub-runs.log").exists()


# ---- identity refusals --------------------------------------------------------------------------------
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


# ---- archive integrity, containment and exclusion -----------------------------------------------
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


def test_export_excludes_secrets_and_refuses_links_and_unlisted_files(tmp_path):
    sid = "66666666-6666-4666-8666-666666666666"
    home = tmp_path / "home"
    base = write_session(home, "/workspace", sid, [b"t"], {"tool-results/r.txt": b"ok", ".hidden": CANARY.encode()})
    (home / ".credentials.json").write_text(CANARY)
    (base / "other-session.jsonl").write_text(CANARY)
    manifest = export_session(home, "/workspace", sid, tmp_path / "export")
    assert [entry["path"].rsplit("/", 1)[-1] for entry in manifest["files"]] == [sid + ".jsonl", "r.txt"]
    assert manifest["excluded"] == 1
    assert CANARY not in "".join(p.read_text("utf-8", "replace") for p in (tmp_path / "export").rglob("*") if p.is_file())
    # Host verification refuses an extra file planted beside the listed ones, and changed bytes.
    (tmp_path / "export" / "projects" / "-workspace" / "planted.txt").write_text("x")
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        read_export(tmp_path / "export", session_id=sid)
    assert refused.value.reason == "archive_unlisted_file"
    (tmp_path / "export" / "projects" / "-workspace" / "planted.txt").unlink()
    (tmp_path / "export" / "projects" / "-workspace" / (sid + ".jsonl")).write_bytes(b"u\n")
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        read_export(tmp_path / "export", session_id=sid)
    assert refused.value.reason == "archive_corrupt"
    probe = tmp_path / "probe"
    try:
        os.symlink(tmp_path / "home" / ".credentials.json", probe)
    except (OSError, NotImplementedError):
        pytest.skip("this host cannot create a symlink fixture")
    os.symlink(home / ".credentials.json", base / sid / "tool-results" / "link.txt")
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        export_session(home, "/workspace", sid, tmp_path / "export-link")
    assert refused.value.reason == "archive_link_refused" and not (tmp_path / "export-link").exists()


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


# ---- ownership, duplicates and crash windows -------------------------------------------------------
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


# ---- review wait, immutable rejection, closure -------------------------------------------------------
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
    store, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner())
    row = adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner())
    reference = row["checkpoints"][-1]["archive"]["ref"]
    frozen = candidate(9)
    owner_sessions.submit("task-1", frozen)
    for step in (lambda: owner_sessions.close("task-1"), lambda: owner_sessions.promote("task-1", "sha256:" + "1" * 64)):
        with pytest.raises(ws.WorkerSessionRefused):
            step()
    decide(store, "review-9", frozen, accepted=True, phase="review_conductor")
    owner_sessions.record_review("task-1", "review-9")
    with pytest.raises(ws.WorkerSessionRefused):
        owner_sessions.close("task-1")  # accepted but not promoted
    owner_sessions.promote("task-1", "sha256:" + "1" * 64)

    def failing(_row):
        raise PermissionError("injected cleanup failure")
    kept = owner_sessions.close("task-1", cleanup=failing)
    assert kept["state"] == ws.ARCHIVAL_PENDING and kept["cleanup"]["state"] == "failed"
    assert kept["cleanup"]["error_type"] == "PermissionError" and kept["cleanup"]["archive_retained"] == reference
    assert owner_sessions.archives.load(reference, session_id=plan["session_id"])["files"]
    closed = owner_sessions.close("task-1", cleanup=lambda _row: None)
    assert closed["state"] == ws.CLOSED and owner_sessions.archives.load(reference, session_id=plan["session_id"])
    assert owner_sessions.close("task-1") == closed


def test_promotion_verifies_the_evidence_reference_when_an_evidence_store_is_given(tmp_path):
    from codex_harness.adapters.artifacts import FileArtifacts
    store = MemoryStore()
    evidence = FileArtifacts(str(tmp_path / "evidence"))
    owner_sessions = WorkerSessions(store, SessionArchives(tmp_path / "archives"), evidence=evidence)
    plan = owner_sessions.begin("task-1", identity(), owner())
    adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner())
    frozen = candidate(10)
    owner_sessions.submit("task-1", frozen)
    decide(store, "review-10", frozen, accepted=True, phase="review_conductor")
    owner_sessions.record_review("task-1", "review-10")
    with pytest.raises((ContractError, OSError)):
        owner_sessions.promote("task-1", "sha256:" + "2" * 64)
    assert owner_sessions.status("task-1")["sessions"][0]["state"] == ws.ACCEPTED
    receipt = evidence.put("promoted evidence", "fixture")
    assert owner_sessions.promote("task-1", receipt["ref"])["promotion"]["verified"] is True


# ---- cumulative usage -------------------------------------------------------------------------------
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


# ---- isolated transport and trusted entry --------------------------------------------------------
def test_entry_binds_task_sessions_to_fixed_paths_and_protocol(tmp_path):
    sid = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    base = {"protocol": iw.SESSION_PROTOCOL, "session_id": sid, "evidence_root": "/evidence"}
    good = {"mode": ws.MODE_RESUME, "session_id": sid, "manifest": {"schema": "x"},
            "restore": "/evidence/" + RESTORE_DIRECTORY, "export": "/evidence/" + EXPORT_DIRECTORY}
    home, bound = entry.task_session({**base, "task_session": good}, {"HOME": "/home/worker"})
    assert Path(home) == Path("/home/worker/.claude") and bound == good
    for request in ({**base, "protocol": iw.PROTOCOL, "task_session": good},  # an older protocol never carries it
                    {**base},  # the session protocol without a session
                    {**base, "task_session": {**good, "export": "/home/worker/other"}},
                    {**base, "task_session": {**good, "restore": "/evidence/../x"}},
                    {**base, "task_session": {**good, "session_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}},
                    {**base, "task_session": {**good, "mode": "latest"}},
                    {**base, "task_session": {**good, "mode": ws.MODE_FRESH}}):
        with pytest.raises(ValueError):
            entry.task_session(request, {"HOME": "/home/worker"})
    with pytest.raises(ValueError):
        entry.task_session({**base, "task_session": good}, {"HOME": "relative"})
    # A session request to an entry is refused on the wire, never answered as a fresh run.
    import io
    out = io.BytesIO()
    request = {**base, "protocol": iw.PROTOCOL, "task_session": good, "prompt": "p", "schema": SCHEMA,
               "timeout": 5, "model": MODEL, "cwd": "/workspace"}
    assert entry.serve(io.BytesIO(json.dumps(request).encode()), out, runtime_factory=None) == 1
    assert json.loads(out.getvalue())["kind"] == "refused"


INNER_SESSION = r'''
import functools, io, json, os, sys
from codex_harness.adapters import isolated_worker_entry as entry
from codex_harness.adapters.claude_cli import ClaudeCodeRuntime
child, workspace, evidence, home = sys.argv[1:5]
os.environ["HOME"] = home
request = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
# Fixture path mapping: a real container always runs in /workspace; here one FIXED host directory
# plays that part for every run (the per-run staging path would be a different transcript store).
request["cwd"], request["evidence_root"] = workspace, evidence
session = request.get("task_session")
if session:
    session["export"] = session["export"].replace("/evidence", evidence, 1)
    if session.get("restore"):
        session["restore"] = session["restore"].replace("/evidence", evidence, 1)
out = io.BytesIO()
factory = functools.partial(ClaudeCodeRuntime, executable=child, launcher=[sys.executable])
code = entry.serve(io.BytesIO(json.dumps(request).encode("utf-8")), out, runtime_factory=factory)
for line in out.getvalue().splitlines():
    message = json.loads(line)
    reported = ((message.get("result") or {}).get("task_session") or {})
    if reported.get("export"):
        reported["export"] = reported["export"].replace(evidence, "/evidence", 1)
    sys.stdout.write(json.dumps(message) + "\n")
sys.stdout.flush()
sys.exit(code)
'''


class SessionDocker(FakeDocker):
    """Injected fake Docker whose 'container' runs the REAL entry and CLI transport against the fixture child."""

    def __init__(self, tmp_path, home, workspace):
        super().__init__(tmp_path)
        self.script.write_text(INNER_SESSION, encoding="utf-8")
        self.home, self.workspace = home, workspace

    def tree(self):
        fake = self

        class Tree:
            @staticmethod
            def spawn(argv, **kwargs):
                container = fake.containers[argv[-1]]
                container["status"] = "running"
                mounts = {m["target"]: m["source"] for m in container["mounts"]}
                kwargs["env"] = {**os.environ, "HOME": str(fake.home)}
                assert Path(mounts[iw.WORKSPACE]).is_dir()
                tree = REAL_TREE.spawn([sys.executable, str(fake.script), str(CHILD), str(fake.workspace),
                                        mounts[iw.EVIDENCE], str(fake.home)], **kwargs)
                fake.process = tree.process
                return tree
        return Tree


def test_isolated_transport_restores_resumes_and_exports_across_container_recreation(tmp_path, monkeypatch):
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    config["limits"] = {**config["limits"], "inner_grace_seconds": 5, "cleanup_seconds": 5}
    repo = tmp_path / "candidate"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "kept.txt").write_text("original\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    store, owner_sessions = sessions(tmp_path)
    container_workspace = tmp_path / "container-workspace"
    container_workspace.mkdir()

    def turn(name, who, prompt):
        plan = owner_sessions.begin("task-1", identity(), who)
        (tmp_path / name).mkdir()
        fake = SessionDocker(tmp_path / name, tmp_path / (name + "-home"), container_workspace)
        monkeypatch.setattr(iw, "_docker", fake)
        monkeypatch.setattr(iw, "ProcessTree", fake.tree())
        runtime = iw.IsolatedClaudeRuntime(config, tmp_path / "runs", model=MODEL, runtime=RUNTIME, max_budget_usd=1.0,
                                           environment={**os.environ, iw.TOKEN_NAME: TOKEN})
        with runtime as opened:
            result = opened.run(prompt, str(repo), SCHEMA, 60, session_id=plan["session_id"], task_session={
                "mode": plan["mode"], "session_id": plan["session_id"],
                "stage": lambda destination: owner_sessions.stage(plan, destination)})
        create = [c["args"] for c in fake.calls if c["args"][0] == "create"][0]
        assert git(repo, "status", "--porcelain") == ""  # nothing imported: the fixture edits no source
        return plan, result, create

    plan, first, create = turn("turn-1", owner("exec-a"), "first")
    assert first["task_session"]["exported"] and first["answer"]["tests"] == ["turn 1", "fresh"]
    assert "/home/worker" not in [a.split("target=")[-1] for a in create if a.startswith("type=bind")]
    row = owner_sessions.checkpoint("task-1", owner("exec-a"), first["task_session"]["export"], usage=None)
    frozen = candidate(11)
    owner_sessions.submit("task-1", frozen)
    decide(store, "review-11", frozen, accepted=False)
    owner_sessions.record_review("task-1", "review-11")
    again, second, create = turn("turn-2", owner("exec-b", 2, 1), "second")
    assert again["mode"] == ws.MODE_RESUME and second["answer"]["tests"] == ["turn 2", "resumed"]
    assert second["session"]["resume"] == "native" and second["session"]["match"]
    assert second["command"]["argv"][second["command"]["argv"].index("--resume") + 1] == plan["session_id"]
    targets = sorted(a.split("target=")[-1] for a in create if a.startswith("type=bind"))
    assert targets == sorted([iw.WORKSPACE, iw.EVIDENCE])  # no home or other task's directory is mounted
    record = iw.run_records(tmp_path / "runs")[-1]
    assert record["state"] == "removed" and Path(second["task_session"]["export"]).is_dir()  # bytes retained
    retained = json.dumps(json.loads(Path(record["record"]).with_name("inner_result.json").read_text("utf-8")))
    assert CANARY not in retained and TOKEN not in retained and '"type": "user"' not in retained
    row = owner_sessions.checkpoint("task-1", owner("exec-b", 2, 1), second["task_session"]["export"], usage=None)
    assert row["checkpoints"][-1]["continuity"] == "prefix_verified" and len(row["checkpoints"]) == 2


def test_isolated_resume_stage_failure_refuses_before_any_container(tmp_path, monkeypatch):
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    repo = tmp_path / "candidate"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    fake = FakeDocker(tmp_path)
    monkeypatch.setattr(iw, "_docker", fake)
    sid = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

    def stage(_destination):
        raise ws.WorkerSessionRefused("archive_corrupt")
    runtime = iw.IsolatedClaudeRuntime(config, tmp_path / "runs", model=MODEL, max_budget_usd=1.0,
                                       environment={**os.environ, iw.TOKEN_NAME: TOKEN})
    with runtime as opened, pytest.raises(iw.IsolationError) as refused:
        opened.run("p", str(repo), SCHEMA, 30, session_id=sid,
                   task_session={"mode": ws.MODE_RESUME, "session_id": sid, "stage": stage})
    assert refused.value.reason_code == "task_session_stage_failed"
    assert not [c for c in fake.calls if c["args"][0] == "create"]
    assert iw.run_records(tmp_path / "runs")[-1]["state"] == "refused"


# ---- CLI: read-only status and explicit close ----------------------------------------------------
def test_cli_status_is_read_only_and_close_requires_promotion(tmp_path):
    from codex_harness import cli
    from codex_harness.adapters import worker_sessions as adapter
    store, owner_sessions = sessions(tmp_path)
    plan = owner_sessions.begin("task-1", identity(), owner())
    adopt_turn(owner_sessions, tmp_path, "t1", plan["session_id"], "/workspace", [b"a"], owner())
    service = SimpleNamespace(store=store)
    before = copy.deepcopy(store.data)
    status = adapter.execute(service, cli.parser().parse_args(["worker-session", "status", "--task-id", "task-1"]),
                             archives=owner_sessions.archives)
    assert status["exit_code"] == 0 and status["sessions"][0]["state"] == ws.CHECKPOINTED
    assert store.data == before
    assert "base64" not in json.dumps(status) and '"a\\n"' not in json.dumps(status)
    close = cli.parser().parse_args(["worker-session", "close", "--task-id", "task-1"])
    with pytest.raises(ws.WorkerSessionRefused) as refused:
        adapter.execute(service, close, archives=owner_sessions.archives)
    printed = adapter.refusal(refused.value)
    assert printed == {"refused": True, "reason": "session_not_promoted", "error_type": "WorkerSessionRefused",
                       "exit_code": 1}
    frozen = candidate(13)
    owner_sessions.submit("task-1", frozen)
    decide(store, "review-13", frozen, accepted=True, phase="review_conductor")
    owner_sessions.record_review("task-1", "review-13")
    owner_sessions.promote("task-1", "sha256:" + "3" * 64)
    closed = adapter.execute(service, close, archives=owner_sessions.archives)
    assert closed["closed"] and closed["archive_retained"].startswith("sha256:")


# ---- executor: the real lease/reservation/settlement path carries the explicit binding --------------
class SessionTransport:
    """LABELLED fake of the isolated transport for executor wiring only: a fresh owned home per run,
    the owner's stage for restore, then the real CLI transport against the fixture child."""

    enters_on_open = False

    def __init__(self, root, count, **kwargs):
        self.root, self.count, self.kwargs = Path(root), count, kwargs

    def __enter__(self):
        self.count.append(1)
        run = self.root / f"run-{len(self.count)}"
        self.inner = ClaudeCodeRuntime(executable=str(CHILD), launcher=[sys.executable],
                                       session_home=str(run / "home" / ".claude"),
                                       **{k: v for k, v in self.kwargs.items() if k != "project_delivery"})
        self.run_directory = run
        self.inner.__enter__()
        return self

    def __exit__(self, *args):
        return self.inner.__exit__(*args)

    def run(self, prompt, cwd, schema, timeout, *, task_session=None, **kwargs):
        binding = {"mode": task_session["mode"], "session_id": task_session["session_id"],
                   "export": str(self.run_directory / EXPORT_DIRECTORY)}
        if task_session["mode"] == ws.MODE_RESUME:
            binding["restore"] = str(self.run_directory / RESTORE_DIRECTORY)
            binding["manifest"] = task_session["stage"](Path(binding["restore"]))
        return self.inner.run(prompt, cwd, schema, timeout, task_session=binding, **kwargs)


def executor_with_sessions(tmp_path, monkeypatch):
    from test_claude_execution import PLAN

    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.observation_spool import MemorySpool
    from codex_harness.application.observations import MemoryDirectory, Observer
    from codex_harness.application.service import Harness
    from codex_harness.bootstrap import organization
    from codex_harness.domain.model import envelope
    from codex_harness.domain.observation import new_process_run_id

    monkeypatch.setenv("ZEUS_CLAUDE_ASSIGNMENTS", "worker:implementation/implement")
    monkeypatch.setenv("ZEUS_CLAUDE_MODEL", MODEL)
    monkeypatch.setenv("ZEUS_CLAUDE_MAX_BUDGET_USD", "1")
    store, workspace, entered = MemoryStore(), tmp_path / "workspace", []
    workspace.mkdir()
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    isolation = SimpleNamespace(config=config, inspector=lambda *args: None,
                                runtime=lambda **kwargs: SessionTransport(tmp_path / "runs", entered, **kwargs))
    git_port = SimpleNamespace(repository=tmp_path, _git=lambda *args, **kwargs: "f" * 40,
                               prepare=lambda *args: {"path": str(workspace), "branch": "harness/t", "base": "f" * 40,
                                                      "task_id": "t"},
                               capture=lambda _workspace: {"revision": "a" * 40, "base": "f" * 40, "tree": "b" * 40})
    observer = Observer(store, MemorySpool(new_process_run_id()), component="test-sessions", directory=MemoryDirectory())
    owner_sessions = WorkerSessions(store, SessionArchives(tmp_path / "archives"))
    executor = Executor(Harness(store, organization()), git_port, FileArtifacts(str(tmp_path / "artifacts")),
                        observer=observer, isolation=isolation, worker_sessions=owner_sessions)
    monkeypatch.setattr(executor, "_inspect_evidence", lambda *a, **k: {"verdict": "not_inspected_in_unit", "claims": 0})
    original = executor._run
    monkeypatch.setattr(executor, "_run", lambda *a, **k: original(
        *a, **{**k, "task_session": {"task_id": "task-1", "repository": "zeus"}, "max_handoffs": 1}))

    def submit():
        message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                           {"plan": dict(PLAN)}, "corr-" + str(len(entered)))
        return executor.workflow.submit(message)
    return SimpleNamespace(executor=executor, store=store, sessions=owner_sessions, entered=entered, submit=submit,
                           workspace=workspace)


def test_executor_threads_the_binding_through_reservation_resume_and_settlement(tmp_path, monkeypatch):
    s = executor_with_sessions(tmp_path, monkeypatch)
    s.submit()
    first = s.executor.execute_one("worker:implementation")
    assert first["status"] == "succeeded" and len(s.entered) == 1
    row = s.sessions.status("task-1")["sessions"][0]
    assert row["state"] == ws.CHECKPOINTED and row["checkpoints"] == 1 and row["owner"] is None
    frozen = candidate(12)
    s.sessions.submit("task-1", frozen)
    # Review wait: an admitted turn is refused before any provider or reservation outcome is used.
    s.submit()
    waiting = s.executor.execute_one("worker:implementation")
    assert waiting["status"] != "succeeded" and len(s.entered) == 1
    with s.store.transaction() as tx:
        reservations = tx.scan("invocation_reservations")
    [refused] = [r for r in reservations if r["status"] == "unsettled_unknown"]
    assert refused["reason"] == "exception:WorkerSessionRefused"  # abandoned, never settled as a call
    decide(s.store, "review-12", frozen, accepted=False)
    s.sessions.record_review("task-1", "review-12")
    s.submit()
    second = s.executor.execute_one("worker:implementation")
    assert second["status"] == "succeeded" and len(s.entered) == 2
    receipt = json.loads((s.executor.artifacts.root / (second["result"]["execution_ref"][7:] + ".txt")).read_text("utf-8"))
    assert receipt["task_session"]["adopted"] and receipt["task_session"]["mode"] == ws.MODE_RESUME
    assert receipt["task_session"]["continuity"] == "prefix_verified" and receipt["session"]["resume"] == "native"
    assert receipt["session_usage"]["basis"] == "cumulative_minus_session_baseline"
    assert receipt["usage"] == {"input_tokens": 100, "output_tokens": 10, "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 5}
    assert receipt["cost"]["reported_usd"] is None and "base64" not in json.dumps(receipt)
    with s.store.transaction() as tx:
        settled = sorted((r for r in tx.scan("invocation_reservations") if r["status"] == "settled"),
                         key=lambda r: r["reserved_at"] if "reserved_at" in r else r["id"])
    totals = sorted(r["usage"]["total_tokens"] for r in settled)
    assert totals == [115, 115]  # turn one (fresh totals) and turn two (delta), never the cumulative 230
    status = s.sessions.status("task-1")["sessions"][0]
    assert status["state"] == ws.CHECKPOINTED and status["checkpoints"] == 2


@pytest.mark.skipif(not os.environ.get("ZEUS_REAL_CLAUDE_SESSION_PROBE"),
                    reason="real two-turn Claude resume probe is owner qualification work; set "
                           "ZEUS_REAL_CLAUDE_SESSION_PROBE to run it deliberately")
def test_real_claude_two_turn_resume_probe(tmp_path):  # pragma: no cover - owner-only, makes real calls
    executable = os.environ["ZEUS_REAL_CLAUDE_SESSION_PROBE"]
    home, workspace = tmp_path / "home", tmp_path / "ws"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    sid = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    runtime = dict(RUNTIME, accounting_mode="subscription")
    model = os.environ.get("ZEUS_CLAUDE_MODEL", "claude-opus-5-5")
    with ClaudeCodeRuntime(model=model, runtime=runtime, executable=executable, session_home=str(home)) as opened:
        opened.run("Remember the word zephyr. Answer with the schema.", str(workspace), SCHEMA, 300, session_id=sid,
                   task_session={"mode": ws.MODE_FRESH, "session_id": sid, "export": str(tmp_path / "e1")})
    manifest = read_export(tmp_path / "e1", session_id=sid)["manifest"]
    with ClaudeCodeRuntime(model=model, runtime=runtime, executable=executable,
                           session_home=str(tmp_path / "home2")) as opened:
        second = opened.run("Which word did I ask you to remember? Put it in summary.", str(workspace), SCHEMA, 300,
                            session_id=sid, task_session={"mode": ws.MODE_RESUME, "session_id": sid,
                                                          "restore": str(tmp_path / "e1"), "manifest": manifest,
                                                          "export": str(tmp_path / "e2")})
    assert "zephyr" in json.dumps(second["answer"]).lower() and second["session"]["match"]
    assert (tmp_path / "e2" / MANIFEST).is_file()

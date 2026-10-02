"""Shared S8 scenario steps (`research.audit_runner`): M7 `adapters/audit_runner.py` (`AuditRunner`: `acquire`, `execute`, `execute_assigned`),
characterized BEFORE the module moves (DESIGN-s8 §24 V29, batch B3). The golden is placement-neutral: it observes SOURCE behaviour only; the
move is the NEXT commits.

- **b1_acquire**: `acquire` (a new target initialised and fetched, an existing target holding the commit, an existing target without it, the
  replay, the invalid repository and commit refused before any spawn, every scripted Git failure; M7 `test_acquire_pins_objects_without_checkout`
  and the `audit_runner` case of `test_piped_git_docker_and_probe_children_are_silent`).
- **b2_inert**: `execute` of the two inert built-ins `source-list` and `source-read` (every argument refusal, the cursor loop over an oversized
  ASCII and Unicode line; M7 `test_inert_reader_never_executes_repository_code`, `test_oversized_source_line_advances_without_losing_unicode`
  and the real-reader case of `tests/test_audit_progress.py`).
- **b3_isolated**: `execute` of any other command (the invalid commands, the manifest mismatch, the staged inert source, the unsafe path, a
  command exit, a bwrap failure blocked, a timeout and a missing runner as 125; M7 `test_namespace_denial_preserves_evidence_and_never_changes_
  isolation` and `test_real_runner_failure_retains_command_evidence`).
- **b4_assigned**: `execute_assigned` (the plain path, and the `host_execution` path through the real `SourceExecutionClient` and
  `SourceExecutions` over a LABELLED workflow store).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a target) driver
builds. LABELLED doubles (nothing here is an actual Git, Docker, bubblewrap or production verification; no clone, network or bwrap ever runs):
- `Git`: the scripted `git`. Its `run(argv, **kwargs)` has `subprocess.run`'s shape and result, answers each subcommand from a recorded
  repository (`init`, `remote add`, `config`, `cat-file`, `rev-parse`, `ls-tree`, `fetch`) and records every spawn. On the reference side the
  driver puts it where M7's `subprocess.run` is called (the adapter's and the verifier's `subprocess` names); on the target side it is the
  injected `processes` port, so the two sides see the SAME calls;
- `Bwrap`: the scripted `run_process` (M7 `tests` patch it the same way): it records the argv, the timeout and a LISTING of the staged source
  (names, kinds, modes, sizes) at call time, and returns or raises what the case scripts;
- `HostStore`: the host source-execution queue (a store whose `source_execution_requests` put is answered by the host), under a workflow that
  has only `store` and `_owned`;
- `classify` is the product's own `classify_isolated_run` on both sides; the artifacts are the product's own `FileArtifacts` over a run-scoped
  directory; the source is built from files (`FILES`) whose manifest and blob envelopes are artifacts of the run.
MASKING (declared here): the run's temporary root is `<root>` in every reported value (`Workspace.scrub`); the random `inspection-*` staging
directory is `<staged>` and the host-dependent `--ro-bind /lib /lib` and `/lib64` argv triples are dropped before an isolated run's output document
is reported, and the receipt's `output_ref` of an isolated run (a hash of that document with the temporary path in it) is replaced by the
digest of the MASKED document; the receipt's environment of an isolated run is reported as whether it equals the bubblewrap digest of this host.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import platform
import subprocess
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import s8_research_program as R

REPO = "https://github.com/fixture/repo"
COMMIT = "1" * 40
TREE = "2" * 40
AUDIT = "audit-1"
RAW_BINARY = b"space\tand\nnewline"
LIBS = (("/lib", "/lib"), ("/lib64", "/lib64"))


def canonical_digest(value) -> str:
    return R.canonical_digest(value)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# (raw path, mode, kind, data): the tracked tree of the labelled repository
FILES = (
    (b"link", "120000", "blob", b"normal"),
    (b"normal", "100644", "blob", b"source"),
    (b"run.sh", "100755", "blob", b"#!/bin/sh\n"),
    (RAW_BINARY, "100644", "blob", b"\xff\x00\xfe"),
    (b"dir/nested.txt", "100644", "blob", b"one\ntwo\n"),
    (b"vendor/sub", "160000", "commit", None),
)


def oid_of(mode, kind, data):
    return "9" * 40 if kind == "commit" else blob_id(data)


# ---- labelled doubles ------------------------------------------------------------------------------------------------------
class Git:
    """LABELLED. The scripted `git` (the adapter's and the verifier's spawns): `subprocess.run`'s shape and result. `repos` holds the
    repositories `init` created (or `plant`ed): `{"origin", "commits"}`; `fail` maps a subcommand key (`init`, `remote`, `config`, `cat-file-e`,
    `cat-file-t`, `rev-parse`, `ls-tree`, `cat-file-blob`, `fetch`) to `(returncode, stderr)` or to an exception it raises; `files` is the tracked
    tree the repository answers with; `calls` records every spawn (argv and keyword arguments)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.calls, self.repos, self.fail, self.files, self.trees = [], {}, {}, FILES, []
        self.kind = b"commit\n"

    def plant(self, directory, origin, commits=()):
        self.repos[str(directory)] = {"origin": origin, "commits": set(commits)}

    def run(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "kwargs": {k: ("PIPE" if v == subprocess.PIPE else v) for k, v in sorted(kwargs.items())}})
        words = list(argv)
        assert words[0] == "git", "an unscripted program"
        words = words[1:]
        if words[:1] == ["--no-replace-objects"]:
            words = words[1:]
        directory = None
        if words[:1] == ["-C"]:
            directory, words = words[1], words[2:]
        while words[:1] == ["-c"]:
            words = words[2:]
        sub = words[0]
        key = sub if sub != "cat-file" else "cat-file-" + words[1].lstrip("-")
        scripted = self.fail.get(key)
        if isinstance(scripted, BaseException):
            raise scripted
        if scripted is not None:
            return self.done(argv, kwargs, scripted[0], b"", scripted[1])
        repo = self.repos.get(directory)
        if key != "init" and repo is None:
            return self.done(argv, kwargs, 128, b"", b"fatal: not a git repository")
        if key == "init":
            self.repos[words[2]] = {"origin": None, "commits": set()}
            return self.done(argv, kwargs)
        if key == "remote":
            repo["origin"] = words[3]
            return self.done(argv, kwargs)
        if key == "config":
            if repo["origin"] is None:
                return self.done(argv, kwargs, 1)
            return self.done(argv, kwargs, out=(repo["origin"] + "\n").encode())
        if key == "cat-file-e":
            return self.done(argv, kwargs, 0 if words[2].split("^")[0] in repo["commits"] else 1)
        if key == "cat-file-t":
            return self.done(argv, kwargs, out=self.kind)
        if key == "rev-parse":
            return self.done(argv, kwargs, out=((self.trees.pop(0) if self.trees else TREE) + "\n").encode())
        if key == "ls-tree":
            lines = [("%s %s %s\t" % (mode, kind, oid_of(mode, kind, data))).encode() + raw for raw, mode, kind, data in self.files]
            return self.done(argv, kwargs, out=b"\0".join(lines) + b"\0")
        if key == "cat-file-blob":
            data = {oid_of(m, k, d): d for _, m, k, d in self.files}[words[2]]
            return self.done(argv, kwargs, out=data)
        if key == "fetch":
            repo["commits"].add(words[-1])
            return self.done(argv, kwargs)
        raise AssertionError("an unscripted git subcommand: " + key)

    @staticmethod
    def done(argv, kwargs, rc=0, out=b"", err=b""):
        if kwargs.get("check") and rc != 0:
            raise subprocess.CalledProcessError(rc, argv, out, err)
        return subprocess.CompletedProcess(argv, rc, out, err)


def staged_listing(directory) -> list:
    """The staged source tree at call time: `[relative name, kind, octal mode, size]`, sorted."""
    base, out = Path(directory), []
    for path in sorted(base.rglob("*")):
        name = os.fsdecode(path.relative_to(base))
        if path.is_symlink():
            out.append([name, "symlink", None, None])
        elif path.is_dir():
            out.append([name, "dir", None, None])
        else:
            out.append([name, "file", oct(path.stat().st_mode & 0o777), path.stat().st_size])
    return out


def mask_argv(argv, directory) -> list:
    """The run's argv with the staging directory as `<staged>` and the host-dependent library binds dropped."""
    out, i = [], 0
    while i < len(argv):
        if argv[i] == "--ro-bind" and (argv[i + 1], argv[i + 2]) in LIBS:
            i += 3
            continue
        out.append(argv[i].replace(str(directory), "<staged>"))
        i += 1
    return out


class Bwrap:
    """LABELLED. The scripted `run_process`: `script` is a list consumed in order of `(returncode, stdout, stderr)` or an exception it raises (the
    default is a clean exit with `executed` output). Every call records the masked argv, the timeout and the staged listing."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.calls, self.script, self.last = [], [], None

    def __call__(self, argv, timeout):
        directory = argv[argv.index("/source") - 1]
        self.last = directory
        self.calls.append({"argv": mask_argv(argv, directory), "timeout": timeout, "staged": staged_listing(directory)})
        step = self.script.pop(0) if self.script else (0, "executed\n", "")
        if isinstance(step, BaseException):
            raise step
        return subprocess.CompletedProcess(argv, step[0], step[1], step[2])


class HostTx:
    def __init__(self, store):
        self.store = store

    def get(self, bucket, key):
        s = self.store
        if bucket == "source_execution_requests":
            row = s.rows.get(key)
            return None if row is None else dict(row)
        if bucket == "research_audits":
            return {"source": asdict(s.source)} if key == AUDIT else None
        if bucket == "research_control":
            return {"status": s.control}
        if bucket == "deployment":
            return {"release_id": "rel-1"}
        return None

    def put(self, bucket, key, row):
        assert bucket == "source_execution_requests", "an unscripted write: " + bucket
        row = dict(row)
        self.store.log.append({k: v for k, v in row.items() if k not in ("at", "task")} | {"task_id": row["task"]["id"]})
        if self.store.answer is not None:   # the host answers the queued request (LABELLED)
            row.update(status=self.store.answer, release_id="rel-1", receipt=asdict(self.store.receipt))
        self.store.rows[key] = row


class HostStore:
    """LABELLED. The queue the host serves: a request is answered at its put (`answer` is the status the host leaves it in, or None to leave it
    queued); `control` is the research activation status."""

    def __init__(self, source, receipt, answer="succeeded", control="active"):
        self.source, self.receipt, self.answer, self.control = source, receipt, answer, control
        self.rows, self.log = {}, []

    @contextlib.contextmanager
    def transaction(self):
        yield HostTx(self)


class HostWorkflow:
    """LABELLED. What `SourceExecutions` reads of a workflow: `store` and `_owned`."""

    def __init__(self, store):
        self.store = store

    def _owned(self, tx, task):
        return task


# ---- the environment ---------------------------------------------------------------------------------------------------------
def make_source(api, artifacts, files=FILES, commit=COMMIT, tree=TREE):
    """The source of `files`: every blob envelope is an artifact, the manifest lists them (as `GitSourceVerifier.inventory` would)."""
    entries = []
    for raw, mode, kind, data in files:
        oid = oid_of(mode, kind, data)
        if kind == "commit":
            entries.append(api.InventoryEntry(b64(raw), mode, oid, None, None))
            continue
        envelope = api.canonical({"version": 1, "encoding": "base64", "bytes_sha256": hashlib.sha256(data).hexdigest(), "data": b64(data)})
        entries.append(api.InventoryEntry(b64(raw), mode, oid, len(data), artifacts.put(envelope, REPO + "@" + commit + ":" + oid)["ref"]))
    manifest = {"version": 1, "repository": REPO, "commit": commit, "tree": tree, "entries": [asdict(e) for e in entries]}
    return api.SourceIdentity(REPO, commit, tree, artifacts.put(api.canonical(manifest), "fixture")["ref"]), entries


def build(api, ws, name, files=FILES, host_execution=False):
    api.fakes.git.reset()
    api.fakes.bwrap.reset()
    base = ws.case(name)
    artifacts = api.FileArtifacts(str(base / "artifacts"))
    root = base / "audit-runner"
    runner = api.make_runner(root, artifacts, host_execution)
    env = SimpleNamespace(api=api, ws=ws, name=name, base=base, root=root, artifacts=artifacts, runner=runner, git=api.fakes.git,
                          bwrap=api.fakes.bwrap, files=files)
    env.source, env.entries = make_source(api, artifacts, files)
    return env


def target_dir(env, repository=REPO, commit=COMMIT):
    return env.root / env.api.digest({"repository": repository, "commit": commit})


def listing(path) -> list:
    path = Path(path)
    return sorted(os.fsdecode(p.relative_to(path)) for p in path.rglob("*")) if path.exists() else None


def spawn_view(env):
    return [{"argv": c["argv"], "kwargs": c["kwargs"]} for c in env.git.calls]


def outcome(fn, *args, view=None, **kwargs):
    """The characterized outcome of one call: the view of its value, or the refusal (type, and the text unless it is an OS error)."""
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:   # the refusal is the characterized result
        out = {"refused": type(exc).__name__}
        if not isinstance(exc, OSError):
            out["message"] = str(exc)[:240]
        if exc.__cause__ is not None:
            out["cause"] = type(exc.__cause__).__name__
        return out
    return {"value": view(value) if view is not None else value}


def step(env, fn, *args, view=None, **kwargs):
    """One call: the outcome, every `git` spawn and `run_process` call it made, and the runner root before and after."""
    env.git.calls.clear()
    env.bwrap.calls.clear()
    before = listing(env.root)
    out = outcome(fn, *args, view=view, **kwargs)
    out["git_spawns"] = spawn_view(env)
    out["bwrap_calls"] = list(env.bwrap.calls)
    out["root_before"], out["root_after"] = before, listing(env.root)
    env.api.advance(0.001)
    return out


def receipt_view(env, receipt):
    """The receipt without its `output_ref`; the output document (masked for an isolated run) and its digest."""
    body = asdict(receipt)
    ref = body.pop("output_ref")
    document = env.artifacts.document(ref)
    if body["runner_id"] == "harness:isolated-source-runner-v1":
        expected = env.api.digest({"runner": "bubblewrap-v1", "platform": platform.uname()})
        body["environment_revision"] = {"is_the_bubblewrap_v1_digest_of_this_host": body["environment_revision"] == expected}
        last = env.bwrap.last
        if "argv" in document:
            document["argv"] = mask_argv(document["argv"], last)
        if "error" in document:
            document["error"] = document["error"].replace(str(last), "<staged>")
    return {"receipt": body, "output": document, "output_digest": canonical_digest(document),
            "output_ref_is_the_hash_of_the_stored_document": ref.startswith("sha256:")}


# ---- b1: acquire -------------------------------------------------------------------------------------------------------------
def acquire_view(env):
    def view(value):
        source, entries, verifier = value
        return {"source": {**asdict(source), "manifest_ref_matches_the_stored_manifest": env.artifacts.document(source.manifest_ref) == {
                    "version": 1, "repository": REPO, "commit": COMMIT, "tree": TREE, "entries": [asdict(e) for e in entries]}},
                "entries": [asdict(e) for e in entries], "verifier": type(verifier).__name__, "verifier_repository": verifier.repository,
                "verifier_runs_the_labelled_git": verifier.git("config", "--get", "remote.origin.url").decode()}
    return view


def b1_acquire(api, ws):
    out = {}
    env = build(api, ws, "acquire-new")
    out["a_new_target_is_initialized_then_fetched"] = step(env, env.runner.acquire, REPO, COMMIT, view=acquire_view(env))
    out["the_new_target_holds_the_remote_and_the_commit"] = {
        k: {"origin": v["origin"], "commits": sorted(v["commits"])} for k, v in env.git.repos.items()}
    out["the_lock_file_and_target"] = listing(env.root)
    out["no_checkout_in_the_target"] = [p for p in listing(target_dir(env)) if p != "inspection"]

    env = build(api, ws, "acquire-present")
    target = target_dir(env)
    target.mkdir(parents=True)
    env.git.plant(target, REPO, [COMMIT])   # LABELLED plant: M7 `test_acquire_pins_objects_without_checkout` clones the fixture repository
    out["an_existing_target_with_the_commit_needs_no_fetch"] = step(env, env.runner.acquire, REPO, COMMIT, view=acquire_view(env))
    out["no_fetch_was_spawned"] = not any("fetch" in c["argv"] for c in env.git.calls)
    out["a_second_acquire_replays_the_same_source"] = step(env, env.runner.acquire, REPO, COMMIT, view=acquire_view(env))

    env = build(api, ws, "acquire-absent")
    target = target_dir(env)
    target.mkdir(parents=True)
    env.git.plant(target, REPO, [])
    out["an_existing_target_without_the_commit_fetches_it"] = step(env, env.runner.acquire, REPO, COMMIT, view=acquire_view(env))

    env = build(api, ws, "acquire-invalid")
    for label, repository, commit in (("a_non_github_repository", "https://evil.example/o/r", COMMIT), ("a_dot_git_repository", REPO + ".git", COMMIT),
                                      ("an_empty_repository", "", COMMIT), ("a_short_commit", REPO, "abc"), ("an_uppercase_commit", REPO, "A" * 40),
                                      ("a_non_string_commit", REPO, None)):
        out["invalid_" + label + "_is_refused_before_any_spawn"] = step(env, env.runner.acquire, repository, commit, view=acquire_view(env))

    for label, fail, plant in (("init_fails", {"init": (128, b"fatal: cannot init")}, None),
                               ("remote_add_fails", {"remote": (3, b"error: remote exists")}, None),
                               ("the_commit_probe_times_out", {"cat-file-e": subprocess.TimeoutExpired(["git"], 30)}, None),
                               ("fetch_fails", {"fetch": (128, b"fatal: could not read from remote repository")}, None),
                               ("the_origin_is_another_repository", {}, "https://github.com/other/repo"),
                               ("the_commit_is_not_a_commit", {"cat-file-t": (0, b"")}, None),
                               ("the_tree_changed", {}, None)):
        env = build(api, ws, "acquire-" + label)
        env.git.fail = dict(fail)
        if label == "the_tree_changed":
            env.git.trees = ["3" * 40, "4" * 40]   # the tree answers differently on the second read
        if label == "the_commit_is_not_a_commit":
            env.git.fail = {}
            env.git.kind = b"tree\n"
        if plant is not None:
            target_dir(env).mkdir(parents=True)
            env.git.plant(target_dir(env), plant, [COMMIT])
        out["acquire_" + label] = step(env, env.runner.acquire, REPO, COMMIT, view=acquire_view(env))
    return out


# ---- b2: the inert built-ins -------------------------------------------------------------------------------------------------
def inert_view(env):
    return lambda receipt: receipt_view(env, receipt)


def b2_inert(api, ws):
    out = {}
    env = build(api, ws, "inert")
    normal, nested, gitlink = b64(b"normal"), b64(b"dir/nested.txt"), b64(b"vendor/sub")
    view = inert_view(env)
    out["source_list_defaults_to_offset_zero"] = step(env, env.runner.execute, env.source, ["source-list"], view=view)
    out["source_list_at_an_offset"] = step(env, env.runner.execute, env.source, ["source-list", "2"], view=view)
    out["source_list_past_the_end"] = step(env, env.runner.execute, env.source, ["source-list", "99"], view=view)
    out["source_list_with_extra_arguments"] = step(env, env.runner.execute, env.source, ["source-list", "1", "2"])
    out["source_list_negative_offset"] = step(env, env.runner.execute, env.source, ["source-list", "-1"])
    out["source_list_non_numeric_offset"] = step(env, env.runner.execute, env.source, ["source-list", "x"])
    out["source_read_the_whole_file"] = step(env, env.runner.execute, env.source, ["source-read", normal, "0"], view=view)
    out["source_read_a_nested_file_from_line_one"] = step(env, env.runner.execute, env.source, ["source-read", nested, "1"], view=view)
    out["source_read_with_a_character_offset"] = step(env, env.runner.execute, env.source, ["source-read", nested, "0", "2"], view=view)
    out["source_read_at_the_end_of_the_file"] = step(env, env.runner.execute, env.source, ["source-read", nested, "2", "0"], view=view)
    out["source_read_a_symlink_entry_as_an_inert_file"] = step(env, env.runner.execute, env.source, ["source-read", b64(b"link"), "0"], view=view)
    out["source_read_a_binary_blob_replaces_undecodable_bytes"] = step(env, env.runner.execute, env.source, ["source-read", b64(RAW_BINARY), "0"], view=view)
    out["source_read_an_unknown_path"] = step(env, env.runner.execute, env.source, ["source-read", "arbitrary-path", "0"])
    out["source_read_a_submodule_path"] = step(env, env.runner.execute, env.source, ["source-read", gitlink, "0"])
    out["source_read_too_few_arguments"] = step(env, env.runner.execute, env.source, ["source-read", normal])
    out["source_read_too_many_arguments"] = step(env, env.runner.execute, env.source, ["source-read", normal, "0", "0", "0"])
    out["source_read_a_line_past_the_end"] = step(env, env.runner.execute, env.source, ["source-read", nested, "3"])
    out["source_read_a_character_past_the_line"] = step(env, env.runner.execute, env.source, ["source-read", nested, "0", "9"])
    out["source_read_a_negative_line"] = step(env, env.runner.execute, env.source, ["source-read", nested, "-1"])
    out["source_read_a_non_numeric_line"] = step(env, env.runner.execute, env.source, ["source-read", nested, "x"])
    out["no_inert_command_spawned_anything"] = {"git": len(env.git.calls), "bwrap": len(env.bwrap.calls)}
    # two reads of one range are one stored document; another range is another (M7 tests/test_audit_progress.py real-reader case)
    first = env.runner.execute(env.source, ["source-read", normal, "0"])
    again = env.runner.execute(env.source, ["source-read", normal, "0"])
    second = env.runner.execute(env.source, ["source-read", nested, "0", "1"])
    out["the_same_range_twice_is_one_document"] = {"same_ref": first.output_ref == again.output_ref, "other_range_differs": first.output_ref != second.output_ref,
                                                   "objects": [env.artifacts.document(r.output_ref)["object_id"] for r in (first, again, second)]}
    # a corrupted blob envelope (LABELLED plant: the artifact says other bytes than its hash)
    bad = api.canonical({"version": 1, "encoding": "base64", "bytes_sha256": "0" * 64, "data": b64(b"tampered")})
    env2 = build(api, ws, "inert-corrupt", files=((b"corrupt", "100644", "blob", b"real"),))
    entry = env2.entries[0]
    manifest = env2.artifacts.document(env2.source.manifest_ref)
    manifest["entries"][0]["artifact_ref"] = env2.artifacts.put(bad, "planted")["ref"]
    source = api.SourceIdentity(REPO, COMMIT, TREE, env2.artifacts.put(api.canonical(manifest), "planted")["ref"])
    out["source_read_a_blob_whose_bytes_do_not_match_their_hash"] = step(env2, env2.runner.execute, source, ["source-read", entry.path, "0"])
    notbase64 = api.canonical({"version": 1, "encoding": "base64", "bytes_sha256": hashlib.sha256(b"").hexdigest(), "data": "!!not base64!!"})
    manifest["entries"][0]["artifact_ref"] = env2.artifacts.put(notbase64, "planted-2")["ref"]
    source = api.SourceIdentity(REPO, COMMIT, TREE, env2.artifacts.put(api.canonical(manifest), "planted-2")["ref"])
    out["source_read_a_blob_that_is_not_base64"] = step(env2, env2.runner.execute, source, ["source-read", entry.path, "0"])

    # the oversized line cursor loop (M7 test_oversized_source_line_advances_without_losing_unicode)
    for label, content in (("ascii", "x" * 24001), ("unicode", "가🙂" * 6001)):
        e = build(api, ws, "inert-oversized-" + label, files=((b"normal", "100644", "blob", content.encode("utf-8")),))
        entry_path = e.entries[0].path
        cursor, chunks, trace = (0, 0), [], []
        for _ in range(5):
            receipt = e.runner.execute(e.source, ["source-read", entry_path, *map(str, cursor)])
            doc = e.artifacts.document(receipt.output_ref)
            chunks.extend(doc["lines"])
            nxt = (doc["next_line"], doc["next_char"])
            trace.append({"bytes": sum(len(s.encode("utf-8")) for s in doc["lines"]), "next": list(nxt), "advanced": nxt > cursor,
                          "partial_last_line": doc["partial_last_line"], "eof": doc["eof"]})
            cursor = nxt
            if cursor[0] == doc["total_lines"]:
                break
        out["oversized_" + label + "_line_advances_without_losing_text"] = {"reads": trace, "reassembled_equals_the_content": "".join(chunks) == content}
    return out


# ---- b3: the isolated path ---------------------------------------------------------------------------------------------------
def b3_isolated(api, ws):
    out = {}
    env = build(api, ws, "isolated")
    view = lambda r: receipt_view(env, r)   # noqa: E731
    for label, command in (("a_string", "ls"), ("a_tuple", ("ls",)), ("an_empty_list", []), ("a_non_string_item", ["ls", 1]),
                           ("an_empty_item", ["ls", ""]), ("none", None)):
        out["invalid_command_" + label + "_is_refused_before_any_staging"] = step(env, env.runner.execute, env.source, command)
    other = api.SourceIdentity(REPO, "5" * 40, TREE, env.source.manifest_ref)
    out["a_source_whose_commit_differs_from_its_manifest"] = step(env, env.runner.execute, other, ["ls"])
    out["a_source_whose_manifest_is_unknown"] = step(env, env.runner.execute, api.SourceIdentity(REPO, COMMIT, TREE, "sha256:" + "d" * 64), ["ls"])
    out["a_staged_inert_source_runs_under_bubblewrap"] = step(env, env.runner.execute, env.source, ["find", "."], view=view)
    out["the_staging_directory_is_removed"] = [name for name in listing(env.root) if name.startswith("inspection-")]
    env.bwrap.script = [(1, "", "cat: missing: No such file")]
    out["a_command_that_exits_non_zero_is_not_a_block"] = step(env, env.runner.execute, env.source, ["cat", "missing"], view=view)
    env.bwrap.script = [(1, "", "bwrap: Creating new namespace failed: Operation not permitted")]
    out["a_namespace_denial_is_blocked_and_keeps_its_evidence"] = step(env, env.runner.execute, env.source, ["find", "."], view=view)
    env.bwrap.script = [(0, "", "bwrap: warning on a clean exit")]
    out["a_clean_exit_with_a_bwrap_diagnostic"] = step(env, env.runner.execute, env.source, ["find", "."], view=view)
    env.bwrap.script = [subprocess.TimeoutExpired(["bwrap"], 120)]
    out["a_timeout_is_a_blocked_125"] = step(env, env.runner.execute, env.source, ["sleep", "999"], view=view)
    env.bwrap.script = [FileNotFoundError(2, "No such file or directory", "bwrap")]
    out["a_missing_runner_is_a_blocked_125"] = step(env, env.runner.execute, env.source, ["find", "."], view=view)
    env.bwrap.script = [PermissionError(13, "Permission denied", "bwrap")]
    out["a_permission_error_is_a_blocked_125"] = step(env, env.runner.execute, env.source, ["find", "."], view=view)
    env.bwrap.script = [ValueError("unexpected")]
    out["any_other_failure_propagates_and_the_staging_directory_is_removed"] = step(env, env.runner.execute, env.source, ["find", "."])
    out["no_staging_directory_is_left"] = [name for name in listing(env.root) if name.startswith("inspection-")]
    env.bwrap.script = [(127, "", "bwrap: execvp nosuch: No such file or directory")]
    out["a_runner_error_exit_is_reported_as_the_commands_127"] = step(env, env.runner.execute, env.source, ["nosuch"], view=view)
    out["the_environment_digest_is_stable_across_runs"] = len({asdict(env.runner.execute(env.source, ["a"]))["environment_revision"]
                                                               for _ in range(2)}) == 1
    out["the_run_never_spawned_git"] = len(env.git.calls)

    # a planted manifest whose paths leave the staging directory (LABELLED: no honest source names them)
    for label, raw in (("a_parent_directory_path", b"../escape"), ("an_absolute_path", b"/etc/escape"), ("a_nested_parent_path", b"dir/../../escape")):
        e = build(api, ws, "isolated-unsafe-" + label, files=((raw, "100644", "blob", b"x"),))
        out["unsafe_" + label + "_is_refused"] = step(e, e.runner.execute, e.source, ["find", "."])
        out["unsafe_" + label + "_leaves_no_staging_directory"] = [name for name in listing(e.root) if name.startswith("inspection-")]
        out["unsafe_" + label + "_called_no_runner"] = len(e.bwrap.calls)
    return out


# ---- b4: execute_assigned ----------------------------------------------------------------------------------------------------
def b4_assigned(api, ws):
    out = {}
    task = {"id": "task-1", "generation": 1, "message": {"what": {"details": {"audit_id": AUDIT}}}}

    env = build(api, ws, "assigned-plain")
    view = lambda r: receipt_view(env, r)   # noqa: E731
    out["the_plain_path_runs_an_inert_command"] = step(env, env.runner.execute_assigned, env.source, ["source-list"], task, None, view=view)
    out["the_plain_path_runs_other_commands_under_bubblewrap"] = step(env, env.runner.execute_assigned, env.source, ["find", "."], task, None, view=view)
    out["the_plain_path_ignores_the_task_and_workflow"] = step(env, env.runner.execute_assigned, env.source, ["source-list"], None, None, view=view)
    out["the_plain_path_refuses_an_invalid_command"] = step(env, env.runner.execute_assigned, env.source, [], task, None)

    env = build(api, ws, "assigned-host", host_execution=True)
    view = lambda r: receipt_view(env, r)   # noqa: E731
    hosted = api.ExecutionReceipt(env.source, "host-env", ["python", "--version"], "docker-readonly", 0, env.artifacts.put("host output", "fixture")["ref"],
                                  "host-docker-runner", False, passed=True, outcome="executed")

    def host(answer="succeeded", control="active"):
        store = HostStore(env.source, hosted, answer, control)
        return store, HostWorkflow(store)

    def hosted_view(store):
        return lambda r: {"receipt_equals_the_hosts": asdict(r) == asdict(hosted), "receipt": asdict(r), "requests": store.log}
    store, workflow = host()
    out["the_host_path_requests_and_returns_the_hosts_receipt"] = step(
        env, env.runner.execute_assigned, env.source, ["python", "--version"], task, workflow, view=hosted_view(store))
    out["the_host_request_row"] = store.log
    out["the_host_path_never_ran_bubblewrap"] = len(env.bwrap.calls)
    store, workflow = host()
    out["an_inert_command_stays_inert_under_host_execution"] = step(env, env.runner.execute_assigned, env.source, ["source-read", b64(b"normal"), "0"],
                                                                      task, workflow, view=view)
    out["no_host_request_for_an_inert_command"] = store.log
    store, workflow = host("cancelled")
    out["a_cancelled_host_request_is_refused"] = step(env, env.runner.execute_assigned, env.source, ["python", "--version"], task, workflow)
    store, workflow = host(control="paused")
    out["a_paused_research_activation_refuses_the_request"] = step(env, env.runner.execute_assigned, env.source, ["python", "--version"], task, workflow)
    out["a_paused_request_was_not_queued"] = store.log
    store, workflow = host()
    foreign = api.SourceIdentity("https://github.com/other/repo", COMMIT, TREE, env.source.manifest_ref)
    out["a_source_that_is_not_the_audits_is_refused"] = step(env, env.runner.execute_assigned, foreign, ["python", "--version"], task, workflow)
    store, workflow = host()
    out["an_invalid_host_command_is_refused"] = step(env, env.runner.execute_assigned, env.source, [""], task, workflow)
    return out


# ---- coverage ----------------------------------------------------------------------------------------------------------------
B1, B2, B3, B4 = "b1_acquire.", "b2_inert.", "b3_isolated.", "b4_assigned."
AUDITS, BACKGROUND, PROGRESS = "tests/test_research_audits.py", "tests/test_background_processes.py", "tests/test_audit_progress.py"


def at(prefix, *names):
    return [prefix + n for n in names]


M7_TESTS = {   # test node -> the golden cases that mirror it, or why it is not in the golden
    AUDITS + "::test_inert_reader_never_executes_repository_code": at(
        B2, "source_list_defaults_to_offset_zero", "source_read_the_whole_file", "source_read_an_unknown_path", "no_inert_command_spawned_anything"),
    AUDITS + "::test_oversized_source_line_advances_without_losing_unicode[ascii]": at(B2, "oversized_ascii_line_advances_without_losing_text"),
    AUDITS + "::test_oversized_source_line_advances_without_losing_unicode[unicode]": at(B2, "oversized_unicode_line_advances_without_losing_text"),
    AUDITS + "::test_real_runner_failure_retains_command_evidence": at(B3, "a_missing_runner_is_a_blocked_125"),
    AUDITS + "::test_namespace_denial_preserves_evidence_and_never_changes_isolation": at(B3, "a_namespace_denial_is_blocked_and_keeps_its_evidence"),
    AUDITS + "::test_acquire_pins_objects_without_checkout": at(B1, "an_existing_target_with_the_commit_needs_no_fetch", "no_fetch_was_spawned"),
    AUDITS + "::test_inventory_receipt_cannot_clear_claimed_test_coverage": {
        "other family": "research.audit_core (service.checkpoint, test_claim_source_list_cannot_attest_a_test); the runner's source-list receipt is " + B2 + "source_list_defaults_to_offset_zero"},
    BACKGROUND + "::test_piped_git_docker_and_probe_children_are_silent[audit_runner]": at(B1, "a_new_target_is_initialized_then_fetched"),
    BACKGROUND + "::test_every_listed_spawn_goes_through_the_helper": {"other family": "static source audit of the spawn helper (host_os / the spawn chokepoint test)"},
    PROGRESS + "::test_distinct_ranges_come_from_the_real_inert_reader_output_and_repeats_add_nothing": at(B2, "the_same_range_twice_is_one_document"),
}


def resolve(result, path):
    node = result
    for part in path.split("."):
        node = node[part]   # a pointer that does not resolve is a driver error, never a silent gap
    return node


def pointers(entry):
    return entry if isinstance(entry, list) else []


def coverage(result) -> dict:
    for entry in M7_TESTS.values():
        for pointer in pointers(entry):
            resolve(result, pointer)
    mirrored = sorted(name for name, entry in M7_TESTS.items() if pointers(entry))
    left_out = {name: entry for name, entry in M7_TESTS.items() if isinstance(entry, dict)}
    return {"m7_tests": M7_TESTS, "mirrored": mirrored, "left_out": left_out,
            "counts": {"m7_test_nodes": len(M7_TESTS), "mirrored": len(mirrored), "left_out": len(left_out)}}


GROUPS = (("b1_acquire", b1_acquire), ("b2_inert", b2_inert), ("b3_isolated", b3_isolated), ("b4_assigned", b4_assigned))


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

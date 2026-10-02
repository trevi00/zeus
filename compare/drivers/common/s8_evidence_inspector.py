"""Shared S8 scenario steps (`evidence.inspector`): M7 `adapters/evidence_inspection.py` (`EvidenceInspector`, `_capture`, `packaged_policy`,
`replay_environment`, `trusted_interpreter`, `replay_argv`), characterized BEFORE the module moves into `evidence.adapters`
(DESIGN-s8 §27 V26 rule E-4; the batch B5a spec). Mirrors the behaviours of M7 `tests/test_evidence_inspection.py` that the adapter itself decides.

- **i1_policy_and_helpers**: the packaged policy (its hash, prefixes and bounds), an unreadable or invalid policy definition, `replay_environment`
  (the allowlist, the candidate `src` binding, no inheritance of the parent's `PYTHONPATH` or secrets), `trusted_interpreter` (every refusal),
  `replay_argv` (only `python -m` is rewritten).
- **i2_file_claims**: file claims against the workspace (checked, hash and range mismatches, no hash claimed, missing, directory, outside the
  workspace, the inspection budget), never the inspector's own cwd.
- **i3_command_claims**: authorized and unauthorized argv, raw bytes kept in the artifact store, invalid UTF-8, a missing executable, a flake, an
  output cap, the denominator.
- **i4_python_replays**: a `python -m` claim runs the trusted interpreter against the candidate `src` whatever PATH and PYTHONPATH say; the finding keeps
  the original argv, the effective argv and the reason; an interpreter-named claim never widens the policy.
- **i5_interpreter_refusal**: a missing trusted interpreter is refused before any child, from `snapshot`, `inspect` and `trusted_interpreter`.
- **i6_deadlines_and_budgets**: the per-command deadline, the claim budget, the aggregate budget and an absent workspace.
- **i7_capture**: `_capture` with a real child: stream receipts, the timeout that terminates the tree, an interruption that reclaims the tree and
  re-raises the original, a tree whose termination is not confirmed (injected), the progress polls and their refusal, the unspawned child (missing
  executable, permission denied, another `OSError`, `TreeOwnershipError` and `TreeOwnershipLeak` raised by spawn).
- **i8_snapshot_identity**: `snapshot` and `identity` per workspace (the interpreter, the cwd, `PYTHONPATH` from the candidate `src` only).
- **i9_inspect_and_seams**: `inspect` aggregation (a malformed claim, the claim budget, the supplied snapshot, `progress` before and after each replay) and the
  injection seams a backend overrides (`_trusted`, `_python`, `_replay`, the keyword arguments of `_replay`, `_archive`).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a target) driver builds.
Children are REAL (this side's own interpreter running fixed one-line programs) through the REAL `ProcessTree` on both sides. The nondeterministic fields
are masked here, declared: the measured remainder inside `timeout after <float>s` becomes `<remaining>`, `duration_seconds` becomes `"<duration>"`, OS pids and group ids become `"<pid>"`, the termination receipt's elapsed
seconds become `"<duration>"`, and the host roots (the temporary directory and this side's interpreter paths) become symbolic names. The artifact
receipt's wall-clock `at` is never reported. Inspection ids, which embed the host path, are checked by recomputing them from the report instead of
being printed."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import threading
import time
from pathlib import Path

from s1_common import outcome, relative

PY = sys.executable
TRUSTED = str(Path(sys.executable).resolve())
PROBE = "zeus_candidate_probe"
PIDISH = {"pid", "group", "pgid", "process_id", "leader"}
DURATIONS = {"duration_seconds", "elapsed_seconds", "seconds"}
# A real child that starts a real grandchild sharing its pipes: the streams reach EOF only when the whole TREE is gone.
HOLDER = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
          "print('started', flush=True); time.sleep(120)")
WATCHDOG_SECONDS = 60


def policy(**replay):
    base = {"version": 1, "replay": {"allowed_argv_prefixes": [[PY, "-c"], ["python", "-m", "pytest"], ["python", "-m", PROBE],
                                                              ["definitely-not-an-executable-zeus"]],
                                     "per_command_seconds": 20, "total_seconds": 60, "max_claims": 8,
                                     "max_output_bytes": 4096, "replays_per_claim": 2},
            "files": {"max_bytes": 1024 * 1024}}
    base["replay"].update(replay)
    return base


def command(code, expected_exit=0):
    return {"kind": "command", "argv": [PY, "-c", code], "expected_exit": expected_exit}


def mask(value):
    """The declared masks: pids and durations only."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in PIDISH and isinstance(item, int) and not isinstance(item, bool):
                out[key] = "<pid>"
            elif key in DURATIONS and isinstance(item, (int, float)) and not isinstance(item, bool):
                out[key] = "<duration>"
            else:
                out[key] = mask(item)
        return out
    if isinstance(value, (list, tuple)):
        return [mask(v) for v in value]
    if isinstance(value, str):
        # the aggregate budget's remainder is a measured float: `timeout after 0.99999...s` (an integral deadline stays literal)
        return re.sub(r"timeout after \d+\.\d{4,}s", "timeout after <remaining>s", value)
    return value


class Ctx:
    def __init__(self, api, root: Path):
        self.api, self.root = api, root
        self.roots = {"ROOT": str(root), "TRUSTED": TRUSTED, "PY": PY}
        self.n = 0

    def fresh(self, name):
        self.n += 1
        path = self.root / f"{self.n:02d}-{name}"
        path.mkdir()
        return path

    def show(self, value):
        return relative(mask(value), self.roots)

    def inspector(self, tmp, spawn=None, interpreter=None, **replay):
        return self.api.make(self.api.FileArtifacts(str(tmp / "artifacts")), policy(**replay), interpreter, spawn=spawn)

    def raw(self, insp, ref):
        return json.loads(insp.artifacts.text(ref, 100000))


def finding_view(ctx, insp, finding):
    """A finding with its archived streams read back (the raw bytes are what the artifact store holds, latin-1 byte-preserving)."""
    out = dict(finding)
    runs = []
    for run in finding.get("runs", []):
        row = dict(run)
        for name in ("stdout", "stderr"):
            if name in row:
                stored = ctx.raw(insp, row[name]["ref"])
                row[name] = {**row[name], "stored": {k: stored[k] for k in ("encoding", "sha256", "bytes", "truncated", "decoding")},
                             "stored_raw_sha256": hashlib.sha256(stored["raw"].encode("latin-1")).hexdigest()}
        runs.append(row)
    if "runs" in out:
        out["runs"] = runs
    return out


# ---- i1 ------------------------------------------------------------------------------------------------------------------
def i1_policy_and_helpers(ctx):
    api, out = ctx.api, {}
    packaged = api.packaged_policy()
    out["packaged"] = {"keys": sorted(packaged), "replay": packaged["replay"], "files": packaged["files"],
                       "policy_hash": packaged["policy_hash"], "policy_file_is_file": api.policy_file().is_file(),
                       "policy_file_name": api.policy_file().name,
                       "file_json_loads": bool(json.loads(api.policy_file().read_text("utf-8")))}
    out["packaged_authorizes"] = {"pytest": api.authorized(["python", "-m", "pytest", "-q"], packaged),
                                  "ruff": api.authorized(["python", "-m", "ruff", "check", "."], packaged),
                                  "rm": api.authorized(["rm", "-rf", "/"], packaged),
                                  "python_c": api.authorized(["python", "-c", "x"], packaged)}
    exact = ["python", "-m", "codex_harness.adapters.worker_profile_metadata"]
    out["metadata_grant"] = {"exact": api.authorized(exact, packaged), "with_arg": api.authorized([*exact, "--help"], packaged),
                             "other_module": api.authorized(["python", "-m", "codex_harness.adapters.worker_profile"], packaged)}
    missing = ctx.root / "no-such-policy.json"
    with api.patched("POLICY_FILE", missing):
        out["policy_unreadable"] = ctx.show(outcome(lambda: api.packaged_policy()))
    invalid = ctx.fresh("invalid-policy") / "policy.json"
    invalid.write_text("{not json", encoding="utf-8")
    with api.patched("POLICY_FILE", invalid):
        out["policy_invalid_json"] = ctx.show(outcome(lambda: api.packaged_policy()))
    invalid.write_text(json.dumps({"version": 2}), encoding="utf-8")
    with api.patched("POLICY_FILE", invalid):
        out["policy_invalid_document"] = ctx.show(outcome(lambda: api.packaged_policy()))
    out["keep_env"] = list(api.KEEP_ENV)
    out["bounds"] = {"cleanup": api.CLEANUP_SECONDS, "reader_join": api.READER_JOIN_SECONDS, "poll": api.POLL_SECONDS}

    base = {"PATH": "/p", "HOME": "/h", "LANG": "C", "ZEUS_DATABASE_URL": "secret", "PYTHONPATH": "/leak", "ProgramData": "pd", "TEMP": "/t",
            "OTHER": "x"}
    out["env_base"] = api.replay_environment(base)
    with_src = ctx.fresh("with-src")
    (with_src / "src").mkdir()
    out["env_with_src"] = ctx.show(api.replay_environment(base, with_src))
    out["env_no_src"] = api.replay_environment(base, ctx.fresh("no-src"))
    src_file = ctx.fresh("src-file")
    (src_file / "src").write_text("x", encoding="utf-8")
    out["env_src_is_file"] = api.replay_environment(base, src_file)
    os_env = api.replay_environment()
    out["env_default_is_filtered_os_environ"] = os_env == {**{k: v for k, v in os.environ.items() if k in api.KEEP_ENV}, "PYTHONIOENCODING": "utf-8"}
    out["env_default_has_no_secret"] = "ZEUS_DATABASE_URL" not in os_env and "PYTHONPATH" not in os_env
    out["env_empty_base"] = api.replay_environment({})

    out["trusted_default"] = str(api.trusted_interpreter()) == TRUSTED
    out["trusted_explicit"] = str(api.trusted_interpreter(PY)) == TRUSTED
    directory = ctx.fresh("a-directory")
    out["trusted_refusals"] = {"missing": ctx.show(outcome(lambda: api.trusted_interpreter(str(ctx.root / "missing-python")))),
                               "directory": ctx.show(outcome(lambda: api.trusted_interpreter(str(directory)))),
                               "relative": ctx.show(outcome(lambda: api.trusted_interpreter("python3")))}
    out["trusted_type"] = type(api.trusted_interpreter()).__name__

    out["replay_argv"] = {
        "python_m": ctx.show(api.replay_argv(["python", "-m", "ruff", "check", "."], TRUSTED)),
        "python_m_only": ctx.show(api.replay_argv(["python", "-m"], TRUSTED)),
        "uv_run": api.replay_argv(["uv", "run", "python", "-m", "pytest"], TRUSTED),
        "python_script": api.replay_argv(["python", "script.py"], TRUSTED),
        "python_alone": api.replay_argv(["python"], TRUSTED),
        "empty": api.replay_argv([], TRUSTED),
        "path_python": api.replay_argv(["/usr/bin/python", "-m", "x"], TRUSTED),
        "copy": api.replay_argv(("python", "-c", "x"), TRUSTED)}
    return out


# ---- i2 ------------------------------------------------------------------------------------------------------------------
def i2_file_claims(ctx):
    tmp = ctx.fresh("files")
    workspace = tmp / "ws"
    (workspace / "src").mkdir(parents=True)
    body = b"line1\nline2\nline3\n"
    (workspace / "src" / "a.txt").write_bytes(body)
    (workspace / "src" / "empty.txt").write_bytes(b"")
    (workspace / "src" / "nonl.txt").write_bytes(b"a\nb")
    (tmp / "a.txt").write_text("outside", encoding="utf-8")  # exists relative to the wrong cwd only
    insp = ctx.inspector(tmp)
    sha = hashlib.sha256(body).hexdigest()
    claims = [{"kind": "file", "path": "src/a.txt", "sha256": sha},
              {"kind": "file", "path": "src/a.txt", "sha256": "b" * 64},
              {"kind": "file", "path": "src/a.txt", "range": {"start": 1, "end": 9}},
              {"kind": "file", "path": "src/a.txt", "range": {"start": 1, "end": 3}},
              {"kind": "file", "path": "src/a.txt"},
              {"kind": "file", "path": "a.txt"},
              {"kind": "file", "path": "src"},
              {"kind": "file", "path": "nope/x.txt"},
              {"kind": "file", "path": "src/../../a.txt"},
              {"kind": "file", "path": "src/empty.txt", "range": {"start": 1, "end": 1}},
              {"kind": "file", "path": "src/nonl.txt", "range": {"start": 1, "end": 2}},
              {"kind": "file", "path": "src/nonl.txt", "sha256": hashlib.sha256(b"a\nb").hexdigest(), "range": {"start": 1, "end": 2}}]
    report = insp.inspect(claims, workspace, {"task_id": "t", "attempt": 1})
    out = {"findings": ctx.show([{k: v for k, v in f.items() if k != "claim"} for f in report["findings"]]),
           "claim_ids_are_digests": [len(f["claim"].get("id", "")) > 8 for f in report["findings"]],
           "context": ctx.show({k: v for k, v in report["context"].items() if k in ("task_id", "attempt", "cwd", "interpreter", "pythonpath")}),
           "policy_hash_equals_inspector": report["policy_hash"] == insp.policy["policy_hash"],
           "has_inspection_id": bool(report["inspection_id"]),
           "verdict": ctx.api.verdict(report["findings"])}
    # the inspection budget
    small = ctx.api.make(ctx.api.FileArtifacts(str(tmp / "small")), {**policy(), "files": {"max_bytes": 10}}, None)
    out["over_budget"] = ctx.show(small.inspect([{"kind": "file", "path": "src/a.txt"}, {"kind": "file", "path": "src/nonl.txt"}], workspace,
                                                {"task_id": "t", "attempt": 1})["findings"])
    out["over_budget"] = [{k: v for k, v in f.items() if k != "claim"} for f in out["over_budget"]]
    # inspect_file directly: the claim shape the parser produces
    parsed = ctx.api.parse_claim({"kind": "file", "path": "src/a.txt", "sha256": sha, "range": {"start": 1, "end": 3}})
    out["inspect_file_direct"] = ctx.show(insp.inspect_file(parsed, workspace))
    out["inspect_file_nul_path"] = ctx.show(insp.inspect_file({"path": "a\x00b", "range": None, "sha256": None}, workspace))
    return out


# ---- i3 ------------------------------------------------------------------------------------------------------------------
def i3_command_claims(ctx):
    tmp = ctx.fresh("commands")
    workspace = tmp / "ws"
    workspace.mkdir()
    insp = ctx.inspector(tmp)
    flaky = workspace / "flake.txt"
    claims = [command("import sys; sys.exit(0)"),
              command("import sys; sys.exit(3)"),
              command('import sys; sys.stdout.buffer.write(b"ok\\xff\\xfe"); sys.exit(0)'),
              {"kind": "command", "argv": ["definitely-not-an-executable-zeus", "--version"], "expected_exit": 0},
              command(f'import os,sys; p={str(flaky)!r}; n=os.path.exists(p); open(p,"w").close(); sys.exit(1 if n else 0)'),
              "rm -rf /",
              command('import sys; sys.stdout.write("x" * 10000); sys.exit(0)'),
              command("import sys; sys.stderr.write('only stderr'); sys.exit(2)", expected_exit=2),
              "python -m pytest --version"]
    report = insp.inspect(claims, workspace, {"task_id": "t", "attempt": 1})
    out = {"findings": [ctx.show(finding_view(ctx, insp, {k: v for k, v in f.items() if k != "claim"})) for f in report["findings"]],
           "denominator": ctx.api.denominator(report["findings"]),
           "environment_names": report["context"]["environment"] and sorted(report["context"]["environment"]) == report["context"]["environment"],
           "has_pythonioencoding": "PYTHONIOENCODING" in report["context"]["environment"],
           "no_secret_names": "ZEUS_DATABASE_URL" not in report["context"]["environment"],
           "pythonpath": report["context"]["pythonpath"]}
    raw = ctx.raw(insp, report["findings"][2]["runs"][0]["stdout"]["ref"])
    out["raw_bytes_kept"] = {"decoded": raw["raw"].encode("latin-1") == b"ok\xff\xfe", "sha256_ok": raw["sha256"] == hashlib.sha256(b"ok\xff\xfe").hexdigest()}
    out["refs_are_sha256"] = all(run["stdout"]["ref"].startswith("sha256:") for run in report["findings"][0]["runs"])
    out["archive_pops_streams"] = all("raw" not in run.get("stdout", {}) and "raw" not in run.get("stderr", {}) for f in report["findings"] for run in f.get("runs", []))
    # `_archive` directly: a run without streams, one stream only, and the input mutated in place
    run = {"failure": "x", "returncode": None}
    out["archive_no_streams"] = insp._archive(dict(run)) == run
    one = {"returncode": 0, "stdout": {"sha256": "a" * 64, "bytes": 1, "truncated": False, "decoding": "utf-8", "raw": "z"}}
    archived = insp._archive(one)
    out["archive_one_stream"] = {"keys": sorted(archived), "stdout_keys": sorted(archived["stdout"]), "input_popped": "stdout" not in one or one is not archived}
    return out


# ---- i4 ------------------------------------------------------------------------------------------------------------------
def probe_workspace(ctx, name):
    workspace = ctx.fresh(name) / "candidate ws"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / (PROBE + ".py")).write_text(
        "import os, sys\n"
        'print("EXECUTABLE=" + sys.executable)\n'
        'print("MODULE=" + os.path.abspath(__file__))\n'
        'print("PYTHONPATH=" + os.environ.get("PYTHONPATH", "<unset>"))\n'
        "sys.exit(0)\n", encoding="utf-8")
    return workspace


def i4_python_replays(ctx):
    out = {}
    workspace = probe_workspace(ctx, "probe")
    tmp = workspace.parent
    saved = {k: os.environ.get(k) for k in ("PATH", "PYTHONPATH")}
    try:
        os.environ["PATH"] = str(tmp / "no-interpreter-here")
        os.environ["PYTHONPATH"] = str(tmp / "parent-leak")
        insp = ctx.inspector(tmp, replays_per_claim=1)
        snapshot = insp.snapshot(workspace)
        out["snapshot"] = {"interpreter_is_trusted": snapshot["identity"]["interpreter"] == snapshot["interpreter"] == TRUSTED,
                           "cwd": ctx.show(snapshot["identity"]["cwd"]),
                           "pythonpath": ctx.show(snapshot["environment"]["PYTHONPATH"]),
                           "no_parent_leak": "parent-leak" not in json.dumps(snapshot["environment"]),
                           "no_src_no_pythonpath": "PYTHONPATH" not in insp.snapshot(tmp)["environment"]}
        # the parent environment changes after the snapshot; the replay still runs under the snapshot
        os.environ["PATH"] = str(tmp / "changed-again")
        os.environ["PYTHONPATH"] = str(tmp / "changed-leak")
        report = insp.inspect(["python -m " + PROBE, {"kind": "command", "argv": [PY, "-m", PROBE], "expected_exit": 0}, "python -m pytest --version"],
                              workspace, {"task_id": "t", "attempt": 1}, environment=snapshot["environment"], interpreter=snapshot["interpreter"])
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    checked, widened, pytest_claim = report["findings"]
    stdout = ctx.raw(insp, checked["runs"][0]["stdout"]["ref"])["raw"].replace("\r", "")
    out["checked"] = ctx.show({k: v for k, v in checked.items() if k not in ("claim", "runs")})
    out["checked_run"] = ctx.show({k: v for k, v in checked["runs"][0].items() if k not in ("stdout", "stderr")})
    out["checked_stdout"] = ctx.show(stdout)
    out["no_leak_in_output"] = "changed-leak" not in stdout and "parent-leak" not in stdout
    out["widened"] = ctx.show({k: v for k, v in widened.items() if k != "claim"})
    out["pytest_claim"] = ctx.show({k: v for k, v in pytest_claim.items() if k not in ("claim", "runs")})
    out["context"] = ctx.show({k: v for k, v in report["context"].items() if k in ("interpreter", "pythonpath", "cwd")})
    return out


# ---- i5 ------------------------------------------------------------------------------------------------------------------
def i5_interpreter_refusal(ctx):
    tmp = ctx.fresh("refusal")
    missing = str(tmp / "missing-python")
    workspace = probe_workspace(ctx, "refusal-probe")
    spawned = []
    api = ctx.api

    def spawn(argv, **kwargs):
        spawned.append(list(argv))
        raise AssertionError("no child may start")

    insp = ctx.inspector(tmp, spawn=spawn, interpreter=missing)
    out = {"snapshot": ctx.show(outcome(lambda: insp.snapshot(workspace))),
           "inspect": ctx.show(outcome(lambda: insp.inspect(["python -m " + PROBE], workspace, {"task_id": "t", "attempt": 1}))),
           "inspect_command": ctx.show(outcome(lambda: insp.inspect_command(api.parse_claim("python -m " + PROBE), workspace, 10.0))),
           "identity": ctx.show(outcome(lambda: insp.identity(workspace))),
           "directory": ctx.show(outcome(lambda: api.trusted_interpreter(str(tmp)))),
           "spawned": spawned}
    # an unauthorized claim is refused by policy before the interpreter is even looked at
    out["unauthorized_first"] = ctx.show(insp.inspect_command(api.parse_claim("rm -rf /"), workspace, 10.0))
    out["spawned_after"] = spawned
    return out


# ---- i6 ------------------------------------------------------------------------------------------------------------------
def i6_deadlines_and_budgets(ctx):
    tmp = ctx.fresh("deadlines")
    workspace = tmp / "ws"
    workspace.mkdir()
    insp = ctx.inspector(tmp, per_command_seconds=1, total_seconds=3, max_claims=2, replays_per_claim=1)
    started = time.monotonic()
    report = insp.inspect([command("import time; time.sleep(30)"), command("import sys; sys.exit(0)"), command("import sys; sys.exit(0)")],
                          workspace, {"task_id": "t", "attempt": 1})
    out = {"fast_enough": time.monotonic() - started < 25,
           "findings": [ctx.show({k: v for k, v in f.items() if k != "claim"}) for f in report["findings"]]}
    exhausted = ctx.inspector(tmp, per_command_seconds=1, total_seconds=1, replays_per_claim=1)
    report = exhausted.inspect([command("import time; time.sleep(5)"), command("import sys; sys.exit(0)")], workspace, {"task_id": "t", "attempt": 1})
    out["aggregate"] = [ctx.show({k: v for k, v in f.items() if k != "claim"}) for f in report["findings"]]
    out["absent_workspace"] = ctx.show(insp.inspect([command("x")], tmp / "absent", {"task_id": "t", "attempt": 1}))
    # the aggregate remainder is spent: `inspect_command` refuses with the budget cause before any child
    out["no_remaining_budget"] = ctx.show(insp.inspect_command(ctx.api.parse_claim(command("pass")), workspace, 0))
    out["negative_remaining"] = ctx.show(insp.inspect_command(ctx.api.parse_claim(command("pass")), workspace, -1.0))
    # replays_per_claim stops at the first failed replay
    twice = ctx.inspector(tmp, per_command_seconds=1, total_seconds=10, replays_per_claim=3)
    report = twice.inspect([{"kind": "command", "argv": ["definitely-not-an-executable-zeus"], "expected_exit": 0}], workspace, {"task_id": "t", "attempt": 1})
    out["stops_after_failure"] = {"runs": len(report["findings"][0]["runs"]), "state": report["findings"][0]["state"]}
    return out


# ---- i7 ------------------------------------------------------------------------------------------------------------------
def capture_view(ctx, run):
    out = dict(run)
    for name in ("stdout", "stderr"):
        if name in out:
            out[name] = {**out[name], "raw": out[name]["raw"]}
    return ctx.show(out)


def spawn_wrapping(api, fired, spawned, interrupt=False, inject_unconfirmed=False):
    real = api.real_spawn()

    def spawn(argv, **kwargs):
        tree = real(argv, **kwargs)
        if interrupt:
            wait, calls = tree.process.wait, []

            def interrupted(timeout=None):
                calls.append(timeout)
                if len(calls) == 1:
                    time.sleep(1.5)
                    raise KeyboardInterrupt
                return wait(timeout=timeout)
            tree.process.wait = interrupted
        original = tree.terminate
        if inject_unconfirmed:
            tree.terminate = lambda reason, **_: {"reason": reason, "confirmed": False, "injected": True}
            tree.close = lambda: None
        watchdog = threading.Timer(WATCHDOG_SECONDS, lambda: (fired.append(tree.process.pid), tree.close(), tree.process.kill()))
        watchdog.daemon = True
        watchdog.start()
        spawned.append((tree, watchdog, original))
        return tree
    return spawn


def i7_capture(ctx):
    api, out = ctx.api, {}
    tmp = ctx.fresh("capture")
    env = api.replay_environment()
    body = b"out" + os.linesep.encode()
    run = api.capture([PY, "-c", "import sys; print('out'); sys.stderr.write('err'); sys.exit(3)"], str(tmp), 20, 4096, env)
    out["normal"] = capture_view(ctx, run)
    out["normal_flags"] = {"sha_ok": run["stdout"]["sha256"] == hashlib.sha256(body).hexdigest(), "raw_ok": run["stdout"]["raw"] == body.decode(),
                           "keys": sorted(run), "cleanup_keys": sorted(run["cleanup"])}
    out["cap"] = capture_view(ctx, api.capture([PY, "-c", "import sys; sys.stdout.write('y' * 5000); sys.stderr.write('z' * 3)"], str(tmp), 20, 100, env))
    out["invalid_utf8"] = capture_view(ctx, api.capture([PY, "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\xfe\\x80')"], str(tmp), 20, 4096, env))
    out["zero_cap"] = capture_view(ctx, api.capture([PY, "-c", "print('dropped')"], str(tmp), 20, 0, env))

    started = time.monotonic()
    timed = api.capture([PY, "-c", HOLDER], str(tmp), 2, 4096, env)
    out["timeout"] = capture_view(ctx, timed)
    out["timeout_fast_enough"] = time.monotonic() - started < WATCHDOG_SECONDS / 2

    # interrupted in wait: the tree is reclaimed, then the ORIGINAL exception is raised with the cleanup attached
    spawned, fired = [], []
    started = time.monotonic()
    try:
        api.capture([PY, "-c", HOLDER], str(tmp), 120, 4096, env, spawn=spawn_wrapping(api, fired, spawned, interrupt=True))
        out["interrupted"] = "not raised"
    except KeyboardInterrupt as exc:
        (tree, watchdog, _), = spawned
        watchdog.cancel()
        out["interrupted"] = {"type": type(exc).__name__, "cleanup": ctx.show(exc.capture_cleanup), "watchdog_fired": fired != [],
                              "fast_enough": time.monotonic() - started < WATCHDOG_SECONDS / 2,
                              "process_ended": tree.process.poll() is not None,
                              "streams_closed": tree.process.stdout.closed and tree.process.stderr.closed}

    # tree termination changes nothing (INJECTED), so the readers cannot finish and the capture is not a success
    spawned, fired = [], []
    with api.patched("READER_JOIN_SECONDS", 1.0):
        started = time.monotonic()
        try:
            run = api.capture([PY, "-c", HOLDER], str(tmp), 2, 4096, env, spawn=spawn_wrapping(api, fired, spawned, inject_unconfirmed=True))
            (tree, watchdog, _), = spawned
            out["unconfirmed"] = {"run": capture_view(ctx, run), "fast_enough": time.monotonic() - started < WATCHDOG_SECONDS / 2,
                                  "stdout_stream_left_open": not tree.process.stdout.closed,
                                  "replay_failed": api.classify_replays([run], 0)[0]}
        finally:
            for tree, watchdog, original in spawned:
                watchdog.cancel()
                original("test cleanup")
                del tree.close
                tree.close()

    # the progress callback: between the bounded polls of the wait, refusal ends the capture the way a cancellation does
    seen = []
    run = api.capture([PY, "-c", "import time; time.sleep(1.3)"], str(tmp), 20, 4096, env, progress=seen.append)
    out["progress_polls"] = {"returncode": run["returncode"], "failure": run["failure"], "all_replay_wait": set(seen) == {"replay_wait"},
                             "at_least_two": len(seen) >= 2}

    class Refuse(Exception):
        pass

    def refuse(label):
        raise Refuse("lost ownership at " + label)

    started = time.monotonic()
    try:
        api.capture([PY, "-c", HOLDER], str(tmp), 120, 4096, env, progress=refuse)
        out["progress_refusal"] = "not raised"
    except Refuse as exc:
        out["progress_refusal"] = {"type": type(exc).__name__, "message": str(exc), "cleanup": ctx.show(exc.capture_cleanup),
                                   "fast_enough": time.monotonic() - started < WATCHDOG_SECONDS / 2}
    # a deadline shorter than one poll
    out["progress_deadline"] = capture_view(ctx, api.capture([PY, "-c", HOLDER], str(tmp), 1, 4096, env, progress=lambda label: None))

    # the unspawned child
    out["executable_missing"] = ctx.show(api.capture(["definitely-not-an-executable-zeus"], str(tmp), 5, 100, env))
    not_exec = tmp / "not-executable"
    not_exec.write_text("#!/bin/sh\n", encoding="utf-8")
    not_exec.chmod(0o644)
    out["permission_denied"] = ctx.show(api.capture([str(not_exec)], str(tmp), 5, 100, env))
    out["cwd_missing"] = ctx.show(api.capture([PY, "-c", "pass"], str(tmp / "no-such-cwd"), 5, 100, env))

    def raising(exc):
        def spawn(argv, **kwargs):
            raise exc
        return spawn
    out["spawn_oserror"] = ctx.show(api.capture([PY], str(tmp), 5, 100, env, spawn=raising(OSError(7, "injected oserror"))))
    out["spawn_ownership"] = ctx.show(api.capture([PY], str(tmp), 5, 100, env, spawn=raising(api.TreeOwnershipError("the process could not be placed in its job object"))))
    detail = {"exit_code": None, "reason": "injected leak"}
    out["spawn_leak"] = ctx.show(api.capture([PY], str(tmp), 5, 100, env,
                                             spawn=raising(api.TreeOwnershipLeak("a process was left behind", detail=detail))))
    out["ownership_classes"] = {"error_base": api.TreeOwnershipError.__mro__[1].__name__, "leak_base": api.TreeOwnershipLeak.__mro__[1].__name__,
                                "leak_is_error": issubclass(api.TreeOwnershipLeak, api.TreeOwnershipError),
                                "error_name": api.TreeOwnershipError.__name__, "leak_name": api.TreeOwnershipLeak.__name__}
    # the same unspawned outcomes through an inspector: one replay, then stop; the failure is the finding's cause
    insp = ctx.inspector(tmp, spawn=raising(api.TreeOwnershipError("no boundary")), replays_per_claim=2)
    workspace = ctx.fresh("unspawned-ws")
    report = insp.inspect([command("pass")], workspace, {"task_id": "t", "attempt": 1})
    out["inspector_ownership"] = ctx.show({k: v for k, v in report["findings"][0].items() if k != "claim"})
    return out


# ---- i8 ------------------------------------------------------------------------------------------------------------------
def i8_snapshot_identity(ctx):
    api = ctx.api
    tmp = ctx.fresh("snapshot")
    plain, withsrc = tmp / "plain", tmp / "with-src"
    plain.mkdir()
    (withsrc / "src").mkdir(parents=True)
    insp = ctx.inspector(tmp)
    out = {}
    for name, cwd in (("plain", plain), ("with_src", withsrc), ("none", None)):
        snap = insp.snapshot(cwd)
        identity = snap["identity"]
        env = snap["environment"]
        out[name] = ctx.show({
            "keys": sorted(snap), "identity_keys": sorted(identity), "tool_keys": sorted(identity["tool"]),
            "policy_hash_ok": identity["policy_hash"] == insp.policy["policy_hash"],
            "environment_names": identity["environment_names"] == sorted(env),
            "environment_digest_ok": identity["environment_digest"] == api.digest(sorted(env.items())),
            "environment_is_replay_environment": env == api.replay_environment(cwd=cwd),
            "interpreter": [identity["interpreter"], snap["interpreter"]],
            "cwd": identity["cwd"],
            "python_ok": identity["tool"]["python"] == platform.python_version(),
            "implementation_ok": identity["tool"]["implementation"] == platform.python_implementation(),
            "executable_digest_ok": identity["tool"]["executable_digest"] == api.digest(TRUSTED),
            "platform_ok": identity["platform"] == platform.platform(),
            "pythonpath": env.get("PYTHONPATH"),
            "identity_equals_identity_method": insp.identity(cwd) == identity})
    out["sensitivity"] = {
        "cwd_changes_identity": insp.identity(plain) != insp.identity(withsrc),
        "src_changes_environment_digest": insp.identity(plain)["environment_digest"] != insp.identity(withsrc)["environment_digest"],
        "policy_changes_hash": ctx.inspector(tmp, per_command_seconds=2).identity(plain)["policy_hash"] != insp.identity(plain)["policy_hash"],
        "default_policy_is_packaged": ctx.api.make(ctx.api.FileArtifacts(str(tmp / "d")), None, None).policy == ctx.api.packaged_policy()}
    other = tmp / "other-python"
    other.write_text("# stands in for another interpreter file\n", encoding="utf-8")
    elsewhere = ctx.inspector(tmp, interpreter=str(other))
    out["other_interpreter"] = ctx.show({"interpreter": elsewhere.identity(plain)["interpreter"],
                                         "digest_ok": elsewhere.identity(plain)["tool"]["executable_digest"] == api.digest(str(other.resolve()))})
    return out


# ---- i9 ------------------------------------------------------------------------------------------------------------------
def i9_inspect_and_seams(ctx):
    api, out = ctx.api, {}
    tmp = ctx.fresh("aggregate")
    workspace = tmp / "ws"
    (workspace / "src").mkdir(parents=True)
    insp = ctx.inspector(tmp, replays_per_claim=1, max_claims=5)
    raws = ["", {"kind": "file", "path": "../x"}, 7, command("import sys; sys.exit(0)"), {"kind": "file", "path": "src"}, "rm -rf /",
            command("pass")]
    labels = []
    report = insp.inspect(raws, workspace, {"task_id": "t", "attempt": 4}, progress=labels.append)
    out["findings"] = [ctx.show({k: v for k, v in f.items() if k not in ("runs",)}) for f in report["findings"]]
    out["progress_labels"] = [label for label in labels if label != "replay_wait"]
    out["context"] = ctx.show({k: v for k, v in report["context"].items() if k not in ("environment_digest", "python")})
    out["context_ok"] = {"python": report["context"]["python"] == sys.version.split()[0],
                         "digest": report["context"]["environment_digest"] == api.digest(sorted(
                             (k, v) for k, v in api.replay_environment(cwd=workspace).items())),
                         "keys": sorted(report["context"])}
    out["report_keys"] = sorted(report)
    recomputed = api.digest([report["context"], report["policy_hash"], [f["claim"] for f in report["findings"]]])
    out["inspection_id_recomputes"] = report["inspection_id"] == recomputed
    absent = insp.inspect([command("x")], tmp / "absent", {"task_id": "t"})
    out["absent_keys"] = sorted(absent)
    out["absent"] = ctx.show(absent)
    # the supplied snapshot is what every replay runs under, whatever the parent has become
    supplied = {"PATH": os.environ.get("PATH", ""), "ZEUS_MARK": "supplied"}
    probe = command('import os, sys; sys.exit(0 if os.environ.get("ZEUS_MARK") == "supplied" and "PYTHONIOENCODING" not in os.environ else 3)')
    given = insp.inspect([probe], workspace, {"task_id": "t"}, environment=supplied, interpreter=PY)
    out["supplied_environment"] = {"state": given["findings"][0]["state"], "context_environment": given["context"]["environment"],
                                   "pythonpath": given["context"]["pythonpath"]}
    out["inspect_does_not_mutate_environment"] = supplied == {"PATH": os.environ.get("PATH", ""), "ZEUS_MARK": "supplied"}

    # the seams a backend overrides (INV-ISOLATED-WORKER-001): _trusted, _python, _replay and its call shape, _archive
    calls = []

    class Seam(api.EvidenceInspector):
        def _trusted(self, candidate):
            calls.append(["trusted", type(candidate).__name__, str(candidate)])
            return Path("/fixture/python")

        def _python(self):
            return "9.99.fixture"

        def _replay(self, argv, cwd, timeout, max_bytes, env, progress=None):
            calls.append(["replay", argv, cwd, timeout, max_bytes, sorted(env), progress is not None])
            return {"failure": None, "terminated": False, "returncode": 0, "duration_seconds": 0.0,
                    "stdout": {"sha256": hashlib.sha256(b"seam").hexdigest(), "bytes": 4, "truncated": False, "decoding": "utf-8", "raw": "seam"},
                    "stderr": {"sha256": hashlib.sha256(b"").hexdigest(), "bytes": 0, "truncated": False, "decoding": "utf-8", "raw": ""},
                    "cleanup": {"confirmed": True}}

    seam = Seam(api.FileArtifacts(str(tmp / "seam-artifacts")), policy(replays_per_claim=2), "named-interpreter")
    report = seam.inspect(["python -m pytest -q", command("pass"), "rm -rf /"], workspace, {"task_id": "s"}, progress=lambda label: None)
    out["seam"] = {"calls": ctx.show(calls), "findings": [ctx.show({k: v for k, v in f.items() if k != "claim"}) for f in report["findings"]],
                   "context": ctx.show({k: report["context"][k] for k in ("interpreter", "python")})}
    calls.clear()
    out["seam_snapshot"] = {"outcome": ctx.show(outcome(lambda: seam.snapshot(workspace))), "seam_calls": calls}
    return out


def run(api, root: Path) -> dict:
    ctx = Ctx(api, root.resolve())
    return {"i1_policy_and_helpers": i1_policy_and_helpers(ctx), "i2_file_claims": i2_file_claims(ctx),
            "i3_command_claims": i3_command_claims(ctx), "i4_python_replays": i4_python_replays(ctx),
            "i5_interpreter_refusal": i5_interpreter_refusal(ctx), "i6_deadlines_and_budgets": i6_deadlines_and_budgets(ctx),
            "i7_capture": i7_capture(ctx), "i8_snapshot_identity": i8_snapshot_identity(ctx),
            "i9_inspect_and_seams": i9_inspect_and_seams(ctx)}

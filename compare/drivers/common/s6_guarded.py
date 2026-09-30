"""Shared S6 scenario steps (`coordination.guarded_launch`): the M7 guarded child launch (DESIGN-s6 §6; TRACE-s6
§7; the Codex S6 condition "one GuardedChildLauncher with byte-equal guarded argv").

- **Argv and files.** The exact guardian argv of the three launchers is recorded:
  - the continuation conductor (`ConductorProcesses.start`);
  - the owner-action assessor (`Assessments.start`);
  - the research tick (`ResearchLaunches.start`).
  Both the default and an explicit bound are covered. Also recorded: the cwd, the environment keys each passes,
  and the launch directory files (`spawn`, `launch.json`, `operation.json`) written BEFORE the spawn.
- **One-shot.** A repeated start of one launch identity is cached. A restarted launcher meets the `spawn` marker and
  never spawns again. A missing token refuses.
- **The guardian itself** (`guard`, run in this process over REAL fixture children, `sys.executable -c ...`):
  - a clean exit; a nonzero exit;
  - a timeout; a stop request;
  - an existing claim (fenced); a missing identity;
  - a command that cannot be created (the `not_created` proof).
  Each produces its exit code and the files the protocol leaves.
- **observe** over each of those directories, and over states built with the protocol's own files:
  - the lock held (running);
  - no claim (it fences: absent);
  - claimed without a proof (unknown);
  - claimed with `unresolved.json`;
  - a proof naming another token (not a proof).
- **The provider probe** of the research launcher over labelled `resolve`/`run` doubles.

Layer: harness (never shipped)

`api` supplies `ConductorProcesses(config, host, *, spawn, environment=None, seconds=None)`,
`Assessments(artifacts, root, *, spawn, environment=None, seconds=None)`,
`ResearchLaunches(root, repository, *, spawn, seconds=None, resolve=None, run=None)`, `guard(directory, command, *,
seconds, sleep)`, `observe(directory)` and `launch_directory(root, launch)`. No model, provider, database or network
is used. The children are `sys.executable -c` one-liners.

**Normalization is explicit, done here and identical on both sides:**
- `sys.executable` → `<python>`;
- this run's temporary root → `<root>`;
- pids → `<pid>`.
Durations are never recorded. A launcher that used another interpreter string or root would still differ.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

LAUNCH = ["%064x" % n for n in range(1, 40)]
PY = sys.executable
# The environment values recorded by name (never the inherited process environment, which differs per side).
ENV_NAMED = ("ZEUS_REPOSITORY", "HARNESS_REPOSITORY", "ZEUS_FIXTURE", "PATH")


class Guardian:
    """LABELLED spawned-guardian handle: `poll()` answers `alive` (None) until `exit()`; nothing runs."""

    def __init__(self):
        self.pid, self.breakaway, self.code = 4242, None, None

    def poll(self):
        return self.code

    def exit(self, code=0):
        self.code = code


class Spawner:
    """LABELLED spawn seam: records argv/cwd/env keys and returns a Guardian handle."""

    def __init__(self):
        self.calls, self.handles = [], []

    def __call__(self, argv, cwd=None, env=None):
        named = {k: env[k] for k in ENV_NAMED if isinstance(env, dict) and k in env}
        self.calls.append({"argv": list(argv), "cwd": cwd, "env_named": named,
                           "env_keys": sorted(env) if isinstance(env, dict) else env})
        handle = Guardian()
        self.handles.append(handle)
        return handle


def normalize(value, root: str):
    if isinstance(value, dict):
        return {normalize(k, root): normalize(v, root) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v, root) for v in value]
    if isinstance(value, str):
        return value.replace(PY, "<python>").replace(root, "<root>")
    return value


def files(directory: Path) -> dict:
    """name -> sha256 of the bytes (JSON documents also by their parsed keys), for every file the protocol left."""
    out = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name not in {"lock", "conduct.log"}:
            data = path.read_bytes()
            # `debt.json` names the guardian's own pid and process boundary: its scrubbed content is recorded by
            # the caller, and here only its keys.
            entry = {} if path.name == "debt.json" else {"sha256": hashlib.sha256(data).hexdigest()}
            if path.suffix == ".json":
                try:
                    entry["keys"] = sorted(json.loads(data))
                except ValueError:
                    entry["keys"] = None
            out[path.name] = entry
        elif path.is_file():
            out[path.name] = {"present": True}
    return out


def document(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def scrub(observed, root: str):
    """An observation without pids, durations or paths; the proof keeps its protocol fields."""
    observed = normalize(observed, root)
    if isinstance(observed, dict):
        observed = {k: v for k, v in observed.items() if k not in {"pid"}}
        proof = observed.get("proof")
        if isinstance(proof, dict):
            observed["proof"] = {k: v for k, v in proof.items() if k not in {"guardian_pid", "pid", "boundary"}}
    return observed


def config(root: str):
    lanes = [{"id": "a", "team": "alpha", "repository": root + "/repo-a", "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": root + "/rt-a"}]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
            "budget": {"per_host": 4, "total": 8}, "lanes": lanes}


JOB = {"id": "op-1", "manifest": {"schema": "urn:zeus:operation:1", "id": "op-1", "note": "LABELLED fixture manifest"}}


def environment(lane, host):
    return {"PATH": "/usr/bin:/bin", "ZEUS_REPOSITORY": lane["repository"], "ZEUS_FIXTURE": "1"}


def launchers(api, root: str) -> dict:
    out = {}
    spawn = Spawner()
    conductor = api.ConductorProcesses(config(root), {}, spawn=spawn, environment=environment)
    first = conductor.start("a", JOB, LAUNCH[0], "tok-1")
    again = conductor.start("a", JOB, LAUNCH[0], "tok-1")
    directory = api.launch_directory(root + "/rt-a", LAUNCH[0])
    out["conductor_default"] = {"first": first, "again": again, "spawn": spawn.calls[-1], "files": files(directory),
                                "launch_json": document(directory / "launch.json"),
                                "operation_json": (directory / "operation.json").read_text(encoding="utf-8")}
    restarted = api.ConductorProcesses(config(root), {}, spawn=spawn, environment=environment)
    out["conductor_restarted"] = {"start": restarted.start("a", JOB, LAUNCH[0], "tok-1"), "spawns": len(spawn.calls)}
    try:
        restarted.start("a", JOB, LAUNCH[1], "")
        out["conductor_no_token"] = {"refused": None}
    except Exception as exc:  # the refusal is the characterized result
        out["conductor_no_token"] = {"refused": type(exc).__name__, "message": str(exc)}
    out["conductor_no_token_files"] = files(api.launch_directory(root + "/rt-a", LAUNCH[1]))
    explicit = api.ConductorProcesses(config(root), {}, spawn=spawn, environment=environment, seconds=12.5)
    explicit.start("a", JOB, LAUNCH[2], "tok-3")
    out["conductor_explicit"] = spawn.calls[-1]
    # Poll while the guardian handle is alive, then after it ended with no guardian ever running (fenced).
    out["conductor_poll_alive"] = explicit.poll("a", LAUNCH[2])
    out["conductor_active"] = explicit.active()
    spawn.handles[-1].exit(0)
    out["conductor_poll_ended"] = explicit.poll("a", LAUNCH[2])
    out["conductor_active_after"] = explicit.active()
    out["conductor_request_stop"] = explicit.request_stop()
    out["conductor_unknown_lane"] = explicit.poll("zz", LAUNCH[3])

    assess_spawn = Spawner()
    assessments = api.Assessments(None, root + "/owner-actions", spawn=assess_spawn)
    out["assessment_default"] = {"start": assessments.start(LAUNCH[4], "dec-1", "corr-1"),
                                 "again": assessments.start(LAUNCH[4], "dec-1", "corr-1"),
                                 "spawn": assess_spawn.calls[-1],
                                 "files": files(api.launch_directory(root + "/owner-actions", LAUNCH[4])),
                                 "launch_json": document(api.launch_directory(root + "/owner-actions", LAUNCH[4])
                                                         / "launch.json")}
    out["assessment_poll_alive"] = assessments.poll(LAUNCH[4])
    assess_spawn.handles[-1].exit(0)
    out["assessment_poll_ended"] = assessments.poll(LAUNCH[4])
    fresh = api.Assessments(None, root + "/owner-actions", spawn=assess_spawn,
                            environment=lambda: {"PATH": "/usr/bin", "ZEUS_FIXTURE": "1"}, seconds=7.0)
    out["assessment_restarted"] = fresh.start(LAUNCH[4], "dec-1", "corr-1")
    fresh.start(LAUNCH[5], "dec-2", "corr-2")
    out["assessment_explicit"] = assess_spawn.calls[-1]

    research_spawn = Spawner()
    research = api.ResearchLaunches(root + "/owner-actions", lambda lane: root + "/repo-" + lane, spawn=research_spawn)
    started = research.start(LAUNCH[6], "rp-b2", "a")
    call = research_spawn.calls[-1]
    out["research_default"] = {"start": started,
                               "spawn": {**call, "env_keys": None,
                                         "env_named": {k: v for k, v in call["env_named"].items() if k != "PATH"}},
                               "env_inherits_process": all(key in call["env_keys"] for key in os.environ),
                               "files": files(api.launch_directory(root + "/owner-actions", LAUNCH[6]))}
    out["research_again"] = research.start(LAUNCH[6], "rp-b2", "a")
    return normalize(out, root)


def probes(api, root: str) -> dict:
    class Done:
        def __init__(self, code):
            self.returncode = code

    def runner(codes):
        calls = []

        def run(argv, **kwargs):
            calls.append([argv[0].replace(root, "<root>"), *argv[1:]])
            code = codes.get(Path(argv[0]).name, 0)
            if code == "timeout":
                raise TimeoutError("labelled")
            if code == "oserror":
                raise OSError("labelled")
            return Done(code)
        return run, calls

    out = {}
    cases = {"ok": ({"codex": root + "/bin/codex", "node": root + "/bin/node"}, {}),
             "codex_unresolved": ({"codex": None, "node": root + "/bin/node"}, {}),
             "node_unresolved": ({"codex": root + "/bin/codex", "node": None}, {}),
             "codex_version_failed": ({"codex": root + "/bin/codex", "node": root + "/bin/node"}, {"codex": 1}),
             "node_unavailable": ({"codex": root + "/bin/codex", "node": root + "/bin/node"}, {"node": "oserror"})}
    for name, (found, codes) in cases.items():
        run, calls = runner(codes)
        launcher = api.ResearchLaunches(root + "/owner-actions", lambda lane: root, spawn=Spawner(),
                                        resolve=lambda found=found: dict(found), run=run)
        out[name] = {"probe": normalize(launcher.probe(), root), "calls": calls}
    return out


def prepared(api, root: str, launch: str, token: str = "tok-g", seconds: float = 30.0) -> Path:
    """A launch directory exactly as a launcher leaves it before the spawn (the conductor's own start)."""
    ConductorProcesses = api.ConductorProcesses
    ConductorProcesses(config(root), {}, spawn=Spawner(), environment=environment, seconds=seconds).start(
        "a", JOB, launch, token)
    return api.launch_directory(root + "/rt-a", launch)


def guardian(api, root: str) -> dict:
    out = {}
    sleep_ = __import__("time").sleep

    def run(name, launch, command, seconds=30.0, before=None):
        directory = prepared(api, root, launch, seconds=seconds)
        if before is not None:
            before(directory)
        code = api.guard(directory, command, seconds=seconds, sleep=sleep_)
        out[name] = {"exit": code, "files": files(directory),
                     "cleanup": scrub(document(directory / "cleanup.json"), root),
                     "unresolved": scrub(document(directory / "unresolved.json"), root),
                     "debt": scrub({k: v for k, v in (document(directory / "debt.json") or {}).items()
                                    if k not in {"guardian_pid", "pid", "boundary"}}, root),
                     "claim": (directory / "claim").read_text(encoding="utf-8") if (directory / "claim").exists()
                     else None,
                     "observe": scrub(api.observe(directory), root)}

    run("exit_0", LAUNCH[10], [PY, "-c", "pass"])
    run("exit_3", LAUNCH[11], [PY, "-c", "import sys; sys.exit(3)"])
    run("timeout", LAUNCH[12], [PY, "-c", "import time; time.sleep(60)"], seconds=0.5)
    run("stopped", LAUNCH[13], [PY, "-c", "import time; time.sleep(60)"],
        before=lambda d: (d / "stop").write_text("stop", encoding="utf-8"))
    run("claimed_before", LAUNCH[14], [PY, "-c", "pass"],
        before=lambda d: (d / "claim").write_text("fenced", encoding="utf-8"))
    run("identity_missing", LAUNCH[15], [PY, "-c", "pass"], before=lambda d: (d / "launch.json").unlink())
    run("not_created", LAUNCH[16], [root + "/bin/does-not-exist"])
    return out


def observations(api, root: str) -> dict:
    from filelock import FileLock

    out = {}
    directory = prepared(api, root, LAUNCH[20])
    lock = FileLock(str(directory / "lock"), is_singleton=False)
    lock.acquire(timeout=0)
    try:
        out["lock_held"] = scrub(api.observe(directory), root)
    finally:
        lock.release()
    out["lock_held_files"] = files(directory)
    directory = prepared(api, root, LAUNCH[21])
    out["no_claim"] = scrub(api.observe(directory), root)
    out["no_claim_again"] = scrub(api.observe(directory), root)
    out["no_claim_files"] = files(directory)
    directory = prepared(api, root, LAUNCH[22])
    (directory / "claim").write_text("child", encoding="utf-8")
    (directory / "exit.json").write_text(json.dumps({"exit_code": 0}), encoding="utf-8")
    out["claimed_no_proof"] = scrub(api.observe(directory), root)
    (directory / "unresolved.json").write_text(json.dumps({"reason_code": "cleanup_unconfirmed"}), encoding="utf-8")
    out["claimed_unresolved"] = scrub(api.observe(directory), root)
    directory = prepared(api, root, LAUNCH[23], token="tok-real")
    (directory / "claim").write_text("child", encoding="utf-8")
    launch = document(directory / "launch.json")
    proof = {"schema": launch["schema"], "kind": "cleanup", "launch": LAUNCH[23], "token": "tok-other",
             "spawned": True, "exit_code": 0, "timed_out": False, "stopped": False, "confirmed": True,
             "parent": {"confirmed": True, "exit_code": 0, "method": None},
             "tree": {"confirmed": True, "exit_code": None, "method": "process_group"}}
    (directory / "cleanup.json").write_text(json.dumps(proof), encoding="utf-8")
    out["foreign_token_proof"] = scrub(api.observe(directory), root)
    (directory / "cleanup.json").write_text(json.dumps({**proof, "token": "tok-real",
                                                        "tree": {"confirmed": False}}), encoding="utf-8")
    out["tree_unconfirmed_proof"] = scrub(api.observe(directory), root)
    (directory / "cleanup.json").write_text(json.dumps({**proof, "token": "tok-real"}), encoding="utf-8")
    out["valid_proof"] = scrub(api.observe(directory), root)
    try:
        api.launch_directory(root, "../escape")
        out["bad_launch_id"] = {"refused": None}
    except Exception as exc:  # the refusal is the characterized result
        out["bad_launch_id"] = {"refused": type(exc).__name__, "message": str(exc)}
    return out


def run(api) -> dict:
    root = tempfile.mkdtemp(prefix="zeus-s6-guarded-")
    try:
        return {"launchers": launchers(api, root), "probes": probes(api, root), "guardian": guardian(api, root),
                "observe": observations(api, root)}
    finally:
        shutil.rmtree(root, ignore_errors=True)

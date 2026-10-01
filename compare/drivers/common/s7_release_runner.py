"""Shared S7 scenario steps (`delivery.release_runner`): M7 `adapters/deployment.py` (`ReleaseRunner`, the file canary,
the check binding, the evaluator pin and controller code refusals), recorded BEFORE the move (DESIGN-s7 §1 V6/V7 and
§2 "Step-6 family plan"; INV-CHECK-001, INV-RELEASE-FILE-CANARY-001, INV-RELEASE-EVALUATOR-MIGRATION-001,
INV-RELEASE-ENVIRONMENT-REVERIFY-001, INV-HOST-DELIVERY-VERIFY-001).

Eight case groups, each case labelled in the result (`mirrors` names the M7 test it copies; a case without `mirrors` is
built from the source):
- `stages`: the order and short-circuit of the stages and EVERY process argv the evaluator would run. M7
  `tests/test_release_runner.py::test_failed_prerequisite_stops_downstream_execution` (install|tests|startup), then the
  same pipeline over the REAL `_check` with the labelled process double (uv sync, docker build, image inspect, start,
  rm, info), the owned-attempt names and labels, the retry answers and the rejection and promotion writes.
- `drift`: `test_runner_refuses_reviewed_candidate_whose_patch_or_target_drifted` (patch|repository) and a tree drift.
- `rebase`: `test_verified_retry_rebases_before_remote_side_effects`, a reviewed release whose main advanced, the
  already-active answer and the verified release with no auto merge.
- `file_canary`: every test of `tests/test_file_canary.py` (74-234), one case per parametrization, plus the canary over
  the REAL `_check` with the process double.
- `check_binding`: the six tests of `tests/test_check_binding.py` (34-201).
- `abandon`: `ReleaseRunner.abandon` (the V5 review owner operations) in each abandonable state, each refusal and a
  missing release.
- `monitor`: `ReleaseRunner.monitor` and `_probe_status`: no deployment, a matching image, a drifted image, the docker
  CLI unavailable and each observation error.
- `pin`: `_test_source` and `resolve_evaluator_pin` (the evaluator pin), `_require_controller_code`, `attempt_resources`
  and the named refusals.

**The process double.** The common module never patches a module. `api.install_process_double(fn)` returns a restore
callable; the reference driver replaces `codex_harness.adapters.deployment.run_process` with `fn`. The double records
each call (argv, cwd, timeout, whether `env` was given, the env KEYS only) and answers with a scripted result. `api.install_seam(name, value)` (restore callable) is the same hook for
the other M7 test seams, by name: `VerificationServices` (M7 `fake_verification_services` and the two services
doubles), `controller_code_revision`, `rmtree` (the cleanup refusal) and `request_rebase` (`Workflow.request_rebase`).
`_check` and `file_canary` replaced on the runner INSTANCE, as M7's tests do, are plain attribute assignments. The
pytest stages of the pipeline cases are answered by an instance wrapper of `_check` (recorded as `via: suite-double`):
the real suite needs a collected manifest and real children. The real suite appears once, in
`check_binding.test_checks_pass_only_by_their_denominator_in_the_bound_workspace`, recorded as its projection (the
verdict and denominator; the receipts carry timings and are not recorded).

**Fixtures (all LABELLED; nothing claims an actual Codex, Docker, GitHub or production verification).**
- `FixtureGit`: the runner's `git` (M7 uses a `SimpleNamespace` of lambdas): `_git`, `inspect`, `review_workspace`,
  `target_identity`, `parent`, `is_ancestor`, `merge`, `publish`; it records each call.
- The container a canary "runs" is a function that writes the files codex plus the handoff would leave (M7 `honest`,
  `write`).
- The check-binding cases use a REAL `GitWorkspace` over a fixture repository (M7 `repository`, `candidate_runner`,
  `runner_with_real_git`), committed under pinned author/committer identity and dates, `GIT_CONFIG_GLOBAL=/dev/null`
  and `GIT_CONFIG_NOSYSTEM=1`; revisions are recorded literally.
- Auth is a placeholder file (`{}`), never a credential. Nothing reaches docker, uv, a git remote or the network.

**Normalization is explicit, done here and identical on both sides.** Pilot 33's rules (`s7_host_targets`, imported):
the temporary root → `<root>`, `sys.executable` → `<python>`, an ISO time string → `<time>`, the `GIT_FIXED` identity.
Added here, each fixture-derived (the fixture learns the value from the very argv it is given):
- the `uv` executable `uv_command()` resolves (bare `uv`, or `~/.local/bin/uv`) → `<uv>`, matched by the executable NAME;
- an artifact reference (`sha256:` + 64 hex) the runner's artifact store returned → `<ref:N>`, N the order it was
  first written in the case (a receipt's digest covers the run's temporary paths and the canary token);
- the canary directory the fixture reads from the `type=bind,source=...,target=/canary` mount → `<canary-dir>`; the
  legacy container name `harness-canary-<12 hex>` (os.urandom) the fixture reads from `--name` → `<canary-name>`; both
  shapes are checked and recorded (`dir_prefix_ok`, `name_shape_ok`);
- the canary token (os.urandom) the fixture reads from `input.txt` → `<token>`, and its sha256 → `<token-sha256>`;
- git's own diagnostic after `Git operation failed (<op>, cwd=...): ` → `<git-diagnostic>`: its wording varies by git
  version and sandbox mount layout (CI ubuntu-latest vs aibox bwrap, found 2026-10-01), and M7 truncates the message
  at 200 characters BEFORE path normalization, so the cut moves with the scratch path length. The error type, the
  git operation and the normalized cwd stay literal;
- the controller's uid:gid in the handoff script (`chown -h UID:GID`) → `<uid>:<gid>`, and a recorded `uid`/`gid` that
  equals the controller's → `<controller-uid>`/`<controller-gid>`;
- a release id (a digest of the candidate, which names temporary paths in the real-git cases) and its first 16
  characters → `<release:NAME>`, NAME being the fixture's own label;
- an env key a call carries beyond the host environment's own passthrough (M7 `ENVIRONMENT_KEYS`) is recorded;
  the host's keys are not (`env_inherits_host`).
Events written to the `events` bucket are recorded by type only (their ids are fresh draws). Durations and waits are
never recorded, and nothing else is masked.

`api` supplies `ReleaseRunner`, `Harness`, `MemoryStore`, `FileArtifacts`, `GitWorkspace`, `organization()`,
`ContractError`, `digest`, `canonical`, `Workflow`, `EvaluatorPinMismatch`, `EvaluatorCodeMismatch`,
`canary_handoff_script`, `canary_postcondition`, `inspect_canary_file`, `attempt_resources`,
`evaluator_patch_sha256`, `resolve_evaluator_pin`, `uv_command`, `pytest_summary`, `classify_test_run`, `is_test_run`,
`bind_revision`, `OUTCOMES`, `install_process_double(fn)`, `install_seam(name, value)` and `reset_ids()`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import s7_host_targets as host

PY, ISO, GIT_FIXED = host.PY, host.ISO, host.GIT_FIXED
GIT_PINNED = {**GIT_FIXED, "GIT_CONFIG_GLOBAL": "/dev/null"}
PASSTHROUGH = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
               "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL", "UV_CACHE_DIR", "PROGRAMDATA", "PROGRAMFILES",
               "PROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH", "ALLUSERSPROFILE", "HTTP_PROXY", "HTTPS_PROXY",
               "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"}
COMPOSE_KEYS = {"HARNESS_CODEX_AUTH", "HARNESS_RUNTIME_DIR", "ZEUS_CODEX_AUTH", "ZEUS_RUNTIME_DIR"}
REF = re.compile(r"sha256:[0-9a-f]{64}")
CHOWN = re.compile(r"(?<=chown -h )\d+:\d+")
GIT_DIAGNOSTIC = re.compile(r"(Git operation failed \([^)]*\): ).*", re.S)
NAME_SHAPE = re.compile(r"harness-canary-[0-9a-f]{12}")
REV_BASE, REV_CAND, REV_MAIN2, REV_EVAL = "b" * 40, "c" * 40, "d" * 40, "e" * 40
TREE, DIFF = "a" * 40, "reviewed diff"
IMAGE_ID = "sha256:" + "1" * 64
OTHER_IMAGE = "sha256:" + "2" * 64
ATTEMPT = "0123456789abcdef" * 2
CHECKS = ["tests", "cli_start", "cli_file_task"]
AUTHOR = "worker:implementation"
REPOSITORY = "github:fixture/repo"
TEXT = "Read input.txt and write its exact contents to output.txt. Return the input contents in value. Do not use network."


def ok(stdout="", stderr=""):
    return (0, stdout, stderr)


# ---- the labelled doubles --------------------------------------------------------------------------------------
class FixtureGit:
    """LABELLED (M7 builds this as a `SimpleNamespace` of lambdas). Records every call."""

    def __init__(self, fx, directory, *, main=REV_BASE, head=REV_CAND, dirty=False, identity=REPOSITORY, remote=None,
                 ancestor=False, review_error=None, inspect=None, parents=None, merge_error=None):
        self.fx, self.directory, self.calls = fx, directory, []
        self.repository, self.remote = directory / "repository", remote
        self.main, self.head, self.dirty, self.identity = main, head, dirty, identity
        self.ancestor, self.review_error, self.parents, self.merge_error = ancestor, review_error, parents or {}, merge_error
        self.inspected = inspect

    def _note(self, name, *args, **kwargs):
        self.calls.append([name, *args, *([kwargs] if kwargs else [])])

    def _git(self, *args, cwd=None):
        self._note("_git", list(args), *([{"cwd": cwd}] if cwd is not None else []))
        if cwd is None:
            return {("rev-parse", "HEAD"): self.main, ("rev-parse", "HEAD^{tree}"): TREE, ("status", "--porcelain"): ""}[args]
        if args == ("rev-parse", "HEAD"):
            if self.head is None:
                raise RuntimeError("fixture: not a git worktree")
            return self.head
        return "M changed.txt" if self.dirty else ""

    def inspect(self, revision, base):
        self._note("inspect", revision, base)
        return self.inspected(revision, base) if self.inspected else {
            "revision": revision, "base": base, "tree": TREE, "diff": DIFF, "files": ["src/change.py"]}

    def parent(self, revision):
        self._note("parent", revision)
        return self.parents.get(revision, REV_BASE)

    def review_workspace(self, revision, name):
        self._note("review_workspace", revision, name)
        if self.review_error:
            raise self.review_error
        path = self.directory / "workspaces" / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def target_identity(self):
        self._note("target_identity")
        return self.identity

    def is_ancestor(self, revision, descendant):
        self._note("is_ancestor", revision, descendant)
        return self.ancestor

    def merge(self, candidate):
        self._note("merge", candidate["revision"])
        if self.merge_error:
            raise self.merge_error
        return {"merged": True, "revision": candidate["revision"], "transport": "local"}

    def publish(self, candidate, title, body):
        self._note("publish", candidate["revision"], title)
        return {"published": True}


def stage_of(argv) -> str:
    argv = [str(a) for a in argv]
    if Path(argv[0]).name == "uv" and argv[1:2] == ["sync"]:
        return "install"
    head = argv[:2]
    if head == ["docker", "build"]:
        return "build"
    if argv[:3] == ["docker", "image", "inspect"]:
        return "image_inspect"
    if head == ["docker", "rm"]:
        return "rm"
    if head == ["docker", "info"]:
        return "info"
    if argv[:3] == ["docker", "compose", "ps"]:
        return "compose_ps"
    if head == ["docker", "inspect"]:
        return "container_inspect"
    if head == ["docker", "exec"]:
        return "exec"
    if head == ["docker", "run"]:
        return "canary_run" if "/bin/sh" in argv else "start"
    return "other"


DEFAULTS = {"install": ok(), "build": ok("built"), "image_inspect": ok(IMAGE_ID + "\n"), "start": ok("codex-cli 1.0"),
            "rm": ok(), "info": ok("27.0.0"), "canary_run": ok(), "compose_ps": ok(""), "container_inspect": ok(IMAGE_ID + "\n"),
            "exec": ok("codex-cli 1.0"), "other": ok()}
DAEMON_DOWN = (1, "", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?")


def fake_services(*args, **kwargs):
    """LABELLED (M7 conftest `fake_verification_services`): unit release orchestration launches no infrastructure."""
    return nullcontext({"database_url": "postgresql://fixture/isolated", "redis_url": "redis://fixture/0"})


class World:
    """One case's runner, store, artifacts, process double and recorders."""

    def __init__(self, fx, name, *, git=None, auth=True, auto_merge=True, service="harness", labels=()):
        self.fx, self.api, self.name = fx, fx.api, name
        self.dir = fx.base / name
        self.dir.mkdir(parents=True)
        self.api.reset_ids()
        store = self.api.MemoryStore()
        self.service = (self.api.Harness(store, self.api.organization()) if service == "harness"
                        else SimpleNamespace(store=store, org=self.api.organization()))
        self.store = store
        self.artifacts = self.api.FileArtifacts(str(self.dir / "artifacts"))
        self.written, self.refs, self.calls = [], {}, []
        original = self.artifacts.put
        self._put = original

        def put(body, source, *args, **kwargs):
            receipt = original(body, source, *args, **kwargs)
            self.refs.setdefault(receipt["ref"], "<ref:%d>" % (len(self.refs) + 1))
            self.written.append({"ref": receipt["ref"], "source": source, "body": body})
            return receipt

        self.artifacts.put = put
        self.auth = self.dir / "fixture-auth.json"
        if auth:
            self.auth.write_text("{}", "utf-8")  # a labelled placeholder, not a credential
        self.git = git if git is not None else FixtureGit(fx, self.dir)
        self.runner = self.api.ReleaseRunner(self.service, self.git, self.artifacts, str(self.auth),
                                             auto_merge=auto_merge, verification_root=str(self.dir / "verification"))
        self.substitutions = [(str(fx.base), "<root>"), (PY, "<python>")]
        for old, new in labels:
            self.label(old, new)
        self.seen = {"canary_dir": None, "name": None}
        self.overrides, self.unexpected = {}, []
        self.before = self.rows()

    # --- normalization ---------------------------------------------------------------------------------------
    def label(self, value, label):
        if isinstance(value, str) and value:
            self.substitutions.append((value, label))

    def n(self, value):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if key in ("uid", "gid") and type(item) is int and item == (os.getuid() if key == "uid" else os.getgid()):
                    out[key] = "<controller-" + key + ">"
                else:
                    out[self.n(key)] = self.n(item)
            return out
        if isinstance(value, (list, tuple)):
            return [self.n(item) for item in value]
        if isinstance(value, Path):
            return self.n(str(value))
        if isinstance(value, str):
            if ISO.match(value):
                return "<time>"
            for old, new in sorted(self.substitutions, key=lambda pair: -len(pair[0])):
                value = value.replace(old, new)
            value = CHOWN.sub("<uid>:<gid>", value)
            value = GIT_DIAGNOSTIC.sub(r"\1<git-diagnostic>", value)
            return REF.sub(lambda m: self.refs.get(m.group(0), m.group(0)), value)
        return value

    def release(self, candidate, policy=None, label=None, *, review=True):
        record = self.runner.releases.propose(candidate, policy or {"checks": CHECKS})
        self.label(record["id"], "<release:%s>" % (label or self.name))
        self.label(record["id"][:16], "<release:%s:16>" % (label or self.name))
        if review:
            for actor in ("lead:improvement", "conductor"):
                self.runner.releases.review(record["id"], actor, candidate["revision"], True, "fixture:review")
        return record

    def verify(self, record, passed=True):
        return self.runner.releases.verify(record["id"], record["candidate"]["revision"], record["policy_hash"],
                                           {name: {"passed": passed, "evidence": "fixture:check"}
                                            for name in record["policy"]["checks"]})

    # --- recorded effects ------------------------------------------------------------------------------------
    def rows(self):
        with self.store.transaction() as tx:
            return {(r["bucket"], r["id"]): r["body"] for r in tx.records()}

    def changed(self):
        after = self.rows()
        rows = [[b, i, body.get("status") if isinstance(body, dict) else None]
                + ([body["failures"]] if isinstance(body, dict) and "failures" in body else [])
                for (b, i), body in sorted(after.items()) if b != "events" and self.before.get((b, i)) != body]
        events = sorted(body.get("type", "?") for (b, i), body in after.items()
                        if b == "events" and (b, i) not in self.before)
        return self.n({"rows": rows, "events": events})

    def artifact_log(self):
        out = []
        for entry in self.written:
            body = entry["body"]
            try:
                content = json.loads(body)
            except ValueError:
                content = body
            out.append({"ref": self.refs[entry["ref"]], "source": entry["source"], "content": self.n(content)})
        return out

    def call(self, via, argv, cwd=None, timeout=None, env=None, **extra):
        argv = [str(a) for a in argv]
        if Path(argv[0]).name == "uv":
            argv[0] = "<uv>"
        host_keys = set(os.environ)
        record = {"via": via, "argv": argv, "cwd": None if cwd is None else str(cwd), "timeout": timeout,
                  "env_given": env is not None}
        if env is not None and argv[:3] == ["docker", "compose", "ps"]:
            # the whole host environment plus the four keys the call sets itself
            record["env_keys"] = sorted(set(env) & COMPOSE_KEYS)
            record["env_inherits_host"] = True
        elif env is not None:
            record["env_keys"] = sorted(set(env) - host_keys - PASSTHROUGH)
            record["env_inherits_host"] = bool(set(env) & (host_keys | PASSTHROUGH))
        record.update(extra)
        self.calls.append(record)
        return record

    # --- the process double ----------------------------------------------------------------------------------
    def script(self, argv):
        stage = stage_of(argv)
        answer = self.overrides.get(stage, DEFAULTS[stage])
        if callable(answer):
            answer = answer(argv)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def double(self, argv, cwd=None, timeout=None, input_text=None, env=None):
        self.call("run_process", argv, cwd, timeout, env, **({"input_text": True} if input_text else {}))
        code, out, err = self.script(argv)
        return SimpleNamespace(returncode=code, stdout=out, stderr=err)

    @contextmanager
    def active(self, **overrides):
        self.overrides.update(overrides)
        restore = self.api.install_process_double(self.double)
        services = self.api.install_seam("VerificationServices", fake_services)
        try:
            yield self
        finally:
            services()
            restore()

    def suite_double(self, verdicts=None):
        """LABELLED: the pytest stages answered by an instance wrapper of `_check` (the real suite needs real children)."""
        original, verdicts, count = self.runner._check, verdicts or {}, []

        def check(argv, cwd=None, timeout=None, env=None, expected_revision=None):
            if "pytest" in [str(a) for a in argv]:
                count.append(1)
                self.call("suite-double", argv, cwd, timeout, env, expected_revision=expected_revision)
                passed = verdicts.get(len(count), True)
                receipt = self.artifacts.put("fixture suite %d" % len(count), "fixture")
                return {"passed": passed, "evidence": receipt["ref"], "outcome": "executed", "binding": {}}
            extra = {} if timeout is None else {"timeout": timeout}
            return original(argv, cwd=cwd, env=env, expected_revision=expected_revision, **extra)

        self.runner._check = check

    def stub_canary(self, passed=True):
        def canary(image, name=None, labels=()):
            self.call("file_canary-double", [image], None, None, None, name=name, labels=list(labels))
            receipt = self.artifacts.put("fixture canary", "fixture")
            return {"passed": passed, "evidence": receipt["ref"], "outcome": "executed", "binding": {},
                    "postcondition_reason": "ok" if passed else "missing"}

        self.runner.file_canary = canary

    def view(self):
        """The recorded calls, normalized once every label the case learned is known."""
        return self.n(self.calls)

    def finish(self, **fields):
        return {**fields, "calls": self.view(), "git_calls": self.n(getattr(self.git, "calls", None)),
                "effects": self.changed(), "artifacts": self.artifact_log()}

    def attempt(self, call):
        try:
            return {"returned": self.n(call())}
        except Exception as exc:  # the refusal is the characterized result
            view = {"type": type(exc).__name__, "message": self.n(str(exc))}
            if getattr(exc, "reason_code", None) is not None:
                view["reason_code"] = exc.reason_code
            return {"raised": view}


class Fx:
    def __init__(self, api, base: Path):
        self.api, self.base, self.serial = api, base, 0

    def world(self, name, **kw):
        return World(self, name, **kw)


def release_candidate(**overrides):
    return {"revision": REV_CAND, "base": REV_BASE, "tree": TREE, "author": AUTHOR, "task_id": "task-1",
            "repository": REPOSITORY, **overrides}


def reviewed(world, *, verified=False, **overrides):
    candidate = release_candidate(diff_hash=world.api.digest(DIFF), **overrides)
    record = world.release(candidate)
    if verified:
        world.verify(record)
        with world.store.transaction() as tx:
            tx.put("images", record["id"], {"id": record["id"], "image": IMAGE_ID, "revision": REV_CAND})
    world.before = world.rows()
    return record


# ---- stages -------------------------------------------------------------------------------------------------------
def case_failed_prerequisite(fx, failure):
    """M7 test_release_runner.py::test_failed_prerequisite_stops_downstream_execution[failure]."""
    world = fx.world("prerequisite-" + failure)
    world.service.store.dsn = "fixture:no-connection"
    world.git = SimpleNamespace(repository=world.dir, _git=lambda *args: "base", inspect=lambda *args: {"tree": "tree"},
                                review_workspace=lambda *args: str(world.dir))
    world.runner.git = world.git
    candidate = {"revision": "candidate", "base": "base", "tree": "tree", "author": AUTHOR}
    release = world.release(candidate)
    stages = []

    def check(argv, *args, **kwargs):
        stage = ("install" if Path(argv[0]).name == "uv" and list(argv[1:2]) == ["sync"] else
                 "tests" if "pytest" in argv else "startup" if argv[:2] == ["docker", "run"] else "build")
        stages.append(stage)
        return {"passed": stage != failure, "evidence": world.artifacts.put(stage, "fixture")["ref"]}

    world.runner._check = check

    def forbidden(*args):
        raise AssertionError("Model canary ran after failed prerequisite")

    world.runner.file_canary = forbidden
    restore = world.api.install_process_double(
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="sha256:image"))
    services = world.api.install_seam("VerificationServices", fake_services)
    try:
        result = world.attempt(lambda: world.runner.run(release["id"]))
    finally:
        services()
        restore()
    return {"mirrors": "test_failed_prerequisite_stops_downstream_execution[%s]" % failure, "result": world.n(result),
            "stages_run": stages, "canary_skipped": (result.get("returned", {}).get("checks", {}).get("cli_file_task") or {}).get("skipped"),
            **world.finish()}


def pipeline(fx, name, *, overrides=None, suite=None, canary=True, git_kwargs=None, auto_merge=True, run="run",
             attempt=None, auth=True):
    world = fx.world(name, auth=auth, auto_merge=auto_merge)
    world.git = FixtureGit(fx, world.dir, **(git_kwargs or {}))
    world.runner.git = world.git
    record = reviewed(world)
    world.suite_double(suite)
    if canary is not None:
        world.stub_canary(canary)
    with world.active(**(overrides or {})):
        if run == "run":
            result = world.attempt(lambda: world.runner.run(record["id"]))
        else:
            result = world.attempt(lambda: world.runner.evaluate(record["id"], attempt=attempt))
    world.run_record = record
    return world, result


def group_stages(fx):
    out = {}
    for failure in ("install", "tests", "startup"):
        out["failed_prerequisite_" + failure] = case_failed_prerequisite(fx, failure)
    plan = [
        ("pipeline_passes_and_promotes", {}, None, True),
        ("install_fails", {"install": (1, "", "error: lockfile out of date")}, None, True),
        ("incumbent_tests_fail", {}, {1: False}, True),
        ("candidate_tests_fail", {}, {2: False}, True),
        ("build_fails_daemon_up", {"build": (1, "", "build error")}, None, True),
        ("build_fails_daemon_down", {"build": DAEMON_DOWN}, None, True),
        ("build_fails_then_docker_info_fails", {"build": (1, "", "build error"), "info": (1, "", "down")}, None, True),
        ("start_fails", {"start": (1, "", "codex: not found")}, None, True),
        ("install_times_out", {"install": subprocess.TimeoutExpired(["uv", "sync"], 120)}, None, True),
        ("docker_cli_missing", {"build": FileNotFoundError("docker")}, None, True),
        ("file_canary_fails", {}, None, False)]
    for name, overrides, suite, canary in plan:
        world, result = pipeline(fx, name, overrides=overrides, suite=suite, canary=canary)
        out[name] = {"result": result, **world.finish()}
    world, result = pipeline(fx, "image_inspect_missing", overrides={"image_inspect": (1, "", "no such image")})
    out["image_inspect_missing"] = {"result": result, **world.finish()}
    world, result = pipeline(fx, "review_workspace_error_legacy", git_kwargs={"review_error": OSError("fixture: clone failed")})
    out["review_workspace_error_legacy"] = {"result": result, **world.finish()}
    # the owned attempt: exact names and labels, the store is never written, the retry codes
    world, result = pipeline(fx, "evaluate_owned_attempt_passes", run="evaluate", attempt=ATTEMPT)
    out["evaluate_owned_attempt_passes"] = {"result": result, **world.finish()}
    world, result = pipeline(fx, "evaluate_legacy_writes_nothing_to_the_store", run="evaluate")
    out["evaluate_legacy_writes_nothing_to_the_store"] = {"result": result, **world.finish()}
    world, result = pipeline(fx, "evaluate_owned_auth_missing", run="evaluate", attempt=ATTEMPT, auth=False)
    out["evaluate_owned_auth_missing"] = {"result": result, **world.finish()}
    world, result = pipeline(fx, "evaluate_owned_review_workspace_error", run="evaluate", attempt=ATTEMPT,
                             git_kwargs={"review_error": OSError("fixture: clone failed")})
    out["evaluate_owned_review_workspace_error"] = {"result": result, **world.finish()}
    world, result = pipeline(fx, "evaluate_owned_build_fails", run="evaluate", attempt=ATTEMPT,
                             overrides={"build": (1, "", "build error")})
    out["evaluate_owned_build_fails"] = {"result": result, **world.finish()}
    world, result = pipeline(fx, "evaluate_owned_install_fails", run="evaluate", attempt=ATTEMPT,
                             overrides={"install": (1, "", "error: lockfile out of date")})
    out["evaluate_owned_install_fails"] = {"result": result, **world.finish()}
    world = fx.world("evaluate_refusals")
    record = world.release(release_candidate(diff_hash=world.api.digest(DIFF)), review=False)
    world.before = world.rows()
    with world.active():
        out["evaluate_refusals"] = {"not_found": world.attempt(lambda: world.runner.evaluate("missing")),
                                    "not_reviewed": world.attempt(lambda: world.runner.evaluate(record["id"])),
                                    "run_not_reviewed": world.attempt(lambda: world.runner.run(record["id"])),
                                    "run_not_found": world.attempt(lambda: world.runner.run("missing")),
                                    **world.finish()}
    world = fx.world("tree_and_attempt_arguments")
    world.git = FixtureGit(fx, world.dir, inspect=lambda r, b: {"revision": r, "base": b, "tree": "other-tree",
                                                                "diff": DIFF, "files": []})
    world.runner.git = world.git
    record = reviewed(world)
    with world.active():
        out["tree_mismatch"] = {"result": world.attempt(lambda: world.runner.run(record["id"])), **world.finish()}
    return out


# ---- drift ---------------------------------------------------------------------------------------------------------
def case_drift(fx, drift):
    """M7 test_release_runner.py::test_runner_refuses_reviewed_candidate_whose_patch_or_target_drifted[drift]."""
    from_api = fx.api
    world = fx.world("drift-" + drift)
    world.git = SimpleNamespace(repository=world.dir, remote="fixture/repo", _git=lambda *args: "base",
                                target_identity=lambda: "github:fixture/repo",
                                inspect=lambda *args: {"tree": "tree", "diff": "reviewed diff"},
                                review_workspace=lambda *args: str(world.dir))
    world.runner.git = world.git
    candidate = {"revision": "candidate", "base": "base", "tree": "tree", "author": AUTHOR,
                 "repository": "github:fixture/repo" if drift == "patch" else "github:other/repo",
                 "diff_hash": from_api.digest("tampered diff" if drift == "patch" else "reviewed diff")}
    release = world.release(candidate)

    def forbidden(*a, **k):
        raise AssertionError("checks ran for a drifted candidate")

    world.runner._check = forbidden
    result = world.attempt(lambda: world.runner.run(release["id"]))
    with world.store.transaction() as tx:
        status = tx.get("releases", release["id"])["status"]
        untouched = not tx.scan("promotion_intents") and not tx.scan("deployment")
    return {"mirrors": "test_runner_refuses_reviewed_candidate_whose_patch_or_target_drifted[%s]" % drift,
            "result": result, "release_status": status, "no_intent_and_no_deployment": untouched, **world.finish()}


def group_drift(fx):
    return {"patch": case_drift(fx, "patch"), "repository": case_drift(fx, "repository")}


# ---- rebase --------------------------------------------------------------------------------------------------------
def group_rebase(fx):
    out = {}
    world = fx.world("verified-retry-rebases")
    seen = []

    def forbidden(*args):
        raise AssertionError("Stale candidate reached remote publication or merge")

    world.git = SimpleNamespace(repository=world.dir, remote="fixture/repo", _git=lambda *args: "advanced-main",
                                publish=forbidden, merge=forbidden)
    world.runner.git = world.git
    candidate = {"revision": "candidate", "base": "old-main", "tree": "tree", "author": AUTHOR, "task_id": "original-task"}
    release = world.release(candidate)
    world.verify(release)
    with world.store.transaction() as tx:
        tx.put("images", release["id"], {"image": "sha256:fixture"})
    world.before = world.rows()

    def rebase(self, task_id, revision):
        seen.append([task_id, revision])
        return {"message_id": "rebase-task"}

    restore = world.api.install_seam("request_rebase", rebase)
    try:
        result = world.attempt(lambda: world.runner.run(release["id"]))
    finally:
        restore()
    out["verified_retry_rebases_before_remote_side_effects"] = {
        "mirrors": "test_verified_retry_rebases_before_remote_side_effects", "result": result, "rebase_requests": seen,
        **world.finish()}

    def seam_case(name, main, *, verified, **kw):
        world = fx.world(name, **{k: kw.pop(k) for k in ("auto_merge",) if k in kw})
        world.git = FixtureGit(fx, world.dir, main=main, **kw)
        world.runner.git = world.git
        record = reviewed(world, verified=verified)
        seen = []
        restore = world.api.install_seam("request_rebase", lambda self, task, rev: seen.append([task, rev]) or {"message_id": "rebase-task"})
        try:
            with world.active():
                world.suite_double()
                world.stub_canary()
                result = world.attempt(lambda: world.runner.run(record["id"]))
        finally:
            restore()
        return {"result": result, "rebase_requests": seen, **world.finish()}

    out["reviewed_release_rebases_when_main_advanced"] = seam_case("reviewed-main-advanced", REV_MAIN2, verified=False)
    out["verified_release_rebases_when_main_advanced"] = seam_case("verified-main-advanced", REV_MAIN2, verified=True)
    out["verified_without_auto_merge_stays_verified"] = seam_case("verified-no-auto-merge", REV_BASE, verified=True,
                                                                  auto_merge=False)
    out["verified_with_auto_merge_promotes"] = seam_case("verified-promotes", REV_BASE, verified=True)
    out["verified_promotion_merge_raises_keeps_a_prepared_intent"] = seam_case(
        "verified-merge-fails", REV_BASE, verified=True, merge_error=ConnectionError("fixture before merge"))
    world = fx.world("verified-image-missing")
    record = reviewed(world)
    world.verify(record)
    world.before = world.rows()
    out["verified_without_an_image_receipt_refuses"] = {"result": world.attempt(lambda: world.runner.run(record["id"])),
                                                        **world.finish()}
    world = fx.world("already-active")
    world.git = FixtureGit(fx, world.dir)
    world.runner.git = world.git
    record = reviewed(world, verified=True)
    world.runner.run(record["id"])
    world.before = world.rows()
    out["active_release_is_already_applied"] = {"result": world.attempt(lambda: world.runner.run(record["id"])),
                                                **world.finish()}
    world = fx.world("remote-intent-uncertain")
    world.git = FixtureGit(fx, world.dir, remote="fixture/repo")
    world.runner.git = world.git
    record = reviewed(world, verified=True)
    with world.store.transaction() as tx:
        tx.put("promotion_intents", record["id"], {
            "id": record["id"], "candidate_hash": world.api.digest(record["candidate"]), "image": IMAGE_ID,
            "candidate": record["candidate"], "expected_active": None, "status": "prepared", "remote": "fixture/repo",
            "external_started": True, "at": "2026-01-01T00:00:00+00:00"})
    world.before = world.rows()
    out["remote_side_effect_needs_reconciliation"] = {"result": world.attempt(lambda: world.runner.run(record["id"])),
                                                      **world.finish()}
    return out


# ---- file canary --------------------------------------------------------------------------------------------------
def canary_root(argv) -> Path:
    mount = next(a for a in argv if str(a).startswith("type=bind,source=") and str(a).endswith(",target=/canary"))
    return Path(mount[len("type=bind,source="):-len(",target=/canary")])


def honest(root, token):  # what codex plus the handoff leave: both files readable by the controller
    (root / "output.txt").write_bytes(token.encode())
    (root / "result.json").write_text(json.dumps({"value": token}), "utf-8")
    os.chmod(root / "output.txt", 0o640)
    os.chmod(root / "result.json", 0o640)


def written(name, data):
    def container(root, token):
        honest(root, token)
        target = root / name
        target.unlink()
        if data is not None:
            target.write_bytes(data(token) if callable(data) else data)
    return container


def listing(root: Path) -> list:
    out = []
    for path in sorted(root.iterdir()):
        info = os.lstat(path)
        out.append({"name": path.name, "type": "symlink" if path.is_symlink() else "dir" if path.is_dir() else "file",
                    "size": info.st_size if path.is_file() and not path.is_symlink() else None})
    return out


def canary_world(fx, name, container, *, rc=0, real_check=False, put_failure=False, owned=False):
    world = fx.world(name, service="namespace", git=SimpleNamespace(calls=[]))
    world.runner.git = None
    state = {"argv": None, "root": None, "token": None, "listing": None, "tokens": []}
    world.state = state

    def container_run(argv):
        argv = [str(a) for a in argv]
        root = canary_root(argv)
        token = (root / "input.txt").read_text("utf-8")
        state.update(argv=argv, root=root, token=token, listing=listing(root),
                     schema=json.loads((root / "schema.json").read_text("utf-8")),
                     dir_mode=format(os.lstat(root).st_mode & 0o7777, "04o"),
                     dir_prefix_ok=root.name.startswith("harness-container-canary-"))
        state["tokens"].append(token)
        world.label(str(root), "<canary-dir>")
        world.label(token, "<token>")
        world.label(hashlib.sha256(token.encode()).hexdigest(), "<token-sha256>")
        if "--name" in argv and not owned:
            legacy = argv[argv.index("--name") + 1]
            world.label(legacy, "<canary-name>")
            state["name_shape_ok"] = bool(NAME_SHAPE.fullmatch(legacy))
        container(root, token)
        # the digests of the bytes the container double left: token-derived, so labelled by file name
        state["file_shas"] = {}
        for name in ("result.json", "output.txt"):
            path = root / name
            if path.is_file() and not path.is_symlink() and os.access(path, os.R_OK):
                state["file_shas"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
                world.label(state["file_shas"][name], "<sha256:%s>" % name)
        return root, token

    def check(argv, cwd=None, **kwargs):
        world.call("_check-double", argv, cwd, kwargs.get("timeout"), kwargs.get("env"))
        container_run(argv)
        receipt = world.artifacts.put(json.dumps({"fixture": "command", "exit_code": rc}), "canary")
        return {"passed": rc == 0, "evidence": receipt["ref"], "outcome": "executed", "binding": {}}

    if not real_check:
        world.runner._check = check
    else:
        world.overrides["canary_run"] = lambda argv: (container_run(argv), (rc, "", ""))[1]
    if put_failure:
        original = world.artifacts.put

        def put(content, kind, *a, **k):
            if kind == "canary-postcondition":
                raise OSError("fixture: store unavailable")
            return original(content, kind, *a, **k)

        world.artifacts.put = put
    return world


def receipt_of(world, answer):
    if not answer.get("postcondition"):
        return None
    text = world.artifacts.read(answer["postcondition"], 0, 32000)
    return json.loads(text), text


def run_canary(world, image="img", *, owned=False, cleanup_refusal=False):
    kwargs = {}
    if owned:
        resources = world.api.attempt_resources(ATTEMPT)
        kwargs = {"name": resources["containers"]["release-canary"], "labels": resources["labels"]["release-canary"]}
    restores = []
    if cleanup_refusal:
        def refuse(path, *args, **kw):
            raise PermissionError("fixture: cleanup refused")
        restores.append(world.api.install_seam("rmtree", refuse))
    try:
        with world.active():
            answer = world.runner.file_canary(image, **kwargs)
    finally:
        for restore in restores:
            restore()
    return answer, kwargs


def canary_record(world, answer, extra=None):
    state = world.state
    receipt = receipt_of(world, answer)
    root = state["root"]
    text = receipt[1] if receipt else ""
    out = {"answer": world.n(answer),
           "receipt": world.n(receipt[0]) if receipt else None,
           "token_in_receipt": bool(state["token"] and state["token"] in text) or "HARNESS_CANARY_" in text,
           "token_sha256_is_the_token_digest": bool(receipt) and receipt[0]["token_sha256"] == hashlib.sha256(
               state["token"].encode()).hexdigest(),
           "receipt_digests_match_the_bytes": {
               name: receipt[0]["files"][name]["sha256"] == digest
               for name, digest in state["file_shas"].items()} if receipt else None,
           "directory_before_container": world.n(state["listing"]), "directory_mode": state["dir_mode"],
           "dir_prefix_ok": state["dir_prefix_ok"], "schema": state["schema"],
           "directory_exists_after": os.path.lexists(root),
           "artifacts": world.artifact_log(), "calls": world.view()}
    if "name_shape_ok" in state:
        out["name_shape_ok"] = state["name_shape_ok"]
    out.update(extra or {})
    if os.path.lexists(root):  # a cleanup the fixture refused: remove it here, never leave a directory behind
        shutil.rmtree(root)
    return out


def canary_case(fx, name, mirrors, container, *, rc=0, owned=False, put_failure=False, cleanup_refusal=False,
                real_check=False, image="img", extra=None):
    world = canary_world(fx, name, container, rc=rc, put_failure=put_failure, real_check=real_check, owned=owned)
    answer, kwargs = run_canary(world, image, owned=owned, cleanup_refusal=cleanup_refusal)
    out = canary_record(world, answer, extra)
    out["mirrors"] = mirrors
    rm = [c["argv"] for c in world.calls if c["argv"][:2] == ["docker", "rm"]]
    out["removed_container_is_the_run_name"] = bool(rm) and rm[0][-1] == world.state["argv"][
        world.state["argv"].index("--name") + 1]
    return out, world


def group_file_canary(fx):
    out = {}
    api, M = fx.api, "tests/test_file_canary.py::"
    # the argv is the same container with only the handoff entrypoint
    case, world = canary_case(fx, "argv", M + "test_the_argv_is_the_same_container_with_only_the_handoff_entrypoint",
                              honest, owned=True, image="sha256:" + "d" * 64)
    argv = world.state["argv"]
    script = f'codex "$@"; rc=$?; chown -h {os.getuid()}:{os.getgid()} /canary/result.json /canary/output.txt 2>/dev/null; exit $rc'
    image = argv.index("sha256:" + "d" * 64)
    resources = api.attempt_resources(ATTEMPT)
    labels = resources["labels"]["release-canary"]
    case["argv_checks"] = {
        "handoff_script_is_the_fixed_wrapper": api.canary_handoff_script(os.getuid(), os.getgid()) == script,
        "entrypoint": argv[image - 2:image], "command_prefix": argv[image + 1:image + 4][:1] + ["<script>"] + argv[image + 3:image + 4],
        "script_is_the_wrapper": argv[image + 2] == script,
        "codex_argv": world.n(argv[image + 4:]), "head": world.n(argv[:5]), "labels": argv[5:9] == [
            "--label", labels[0], "--label", labels[1]],
        "auth_mount": f"type=bind,source={world.runner.auth},target=/root/.codex/auth.json,readonly" in argv,
        "memory_cpus": argv[argv.index("--memory"):argv.index("--memory") + 4],
        "codex_argv_is_the_fixed_text": argv[-1] == TEXT}
    out["test_the_argv_is_the_same_container_with_only_the_handoff_entrypoint"] = case
    for uid, gid in ((-1, 0), ("1000", 1000), (1000, None), (True, 0)):
        label = "handoff_ids_%s_%s" % (uid, gid)
        w = fx.world(label)
        out[label] = {"mirrors": M + "test_the_handoff_ids_are_validated_integers[%r-%r]" % (uid, gid),
                      "result": w.attempt(lambda: api.canary_handoff_script(uid, gid))}

    def mode_0600(root, token):
        honest(root, token)
        os.chmod(root / "result.json", 0o600)  # the handoff made the controller the owner

    out["forced_0600_result_is_readable"], _ = canary_case(
        fx, "mode-0600", M + "test_a_forced_0600_result_is_readable_after_the_handoff", mode_0600)
    table = [
        ("result_missing", written("result.json", None)), ("output_missing", written("output.txt", None)),
        ("result_not_json", written("result.json", b"{not json")), ("result_not_utf8", written("result.json", b"\xff\xfe")),
        ("result_list", written("result.json", b'["HARNESS"]')), ("result_string", written("result.json", b'"HARNESS"')),
        ("result_no_value", written("result.json", b'{"other": 1}')),
        ("result_value_mismatch", written("result.json", b'{"value": "HARNESS_CANARY_0000000000000000"}')),
        ("result_value_not_text", written("result.json", lambda t: json.dumps({"value": [t]}).encode())),
        ("output_bytes_mismatch", written("output.txt", lambda t: (t + "\n").encode()))]
    for label, container in table:
        out["postcondition_" + label], _ = canary_case(
            fx, "post-" + label, M + "test_each_postcondition_failure_is_named_and_never_a_pass[%s]" % label, container)
    outside = {}

    def symlink(root, token):
        honest(root, token)
        target = root.parent / ("outside-" + root.name + ".txt")
        outside["path"] = target
        target.write_bytes(token.encode())
        (root / "output.txt").unlink()
        (root / "output.txt").symlink_to(target)

    out["symlink_is_refused_not_followed"], _ = canary_case(fx, "symlink", M + "test_a_symlink_is_refused_not_followed",
                                                              symlink)
    out["symlink_is_refused_not_followed"]["outside_target_survives"] = outside["path"].exists()
    outside["path"].unlink()

    def directory(root, token):
        honest(root, token)
        (root / "result.json").unlink()
        (root / "result.json").mkdir()

    out["directory_is_not_regular"], _ = canary_case(fx, "directory", M + "test_a_directory_is_not_regular", directory)
    if os.geteuid() == 0:
        out["unreadable_file_is_named_by_its_error_type"] = {"unreachable": "root reads a 000 file (M7 skips it)"}
    else:
        def unreadable(root, token):  # F6: a root-owned 0640 file without the handoff
            honest(root, token)
            os.chmod(root / "output.txt", 0o000)

        out["unreadable_file_is_named_by_its_error_type"], _ = canary_case(
            fx, "unreadable", M + "test_an_unreadable_file_is_named_by_its_error_type", unreadable)
    out["failed_command_keeps_its_evidence"], _ = canary_case(
        fx, "failed-command", M + "test_a_failed_command_keeps_its_evidence_and_still_records_the_postcondition", honest, rc=7)
    out["receipt_has_no_token_or_raw_contents"], world = canary_case(
        fx, "no-token", M + "test_the_receipt_has_no_token_or_raw_contents", honest)
    record = out["receipt_has_no_token_or_raw_contents"]
    record["file_entry_keys"] = sorted(record["receipt"]["files"]["result.json"])
    record["output_sha256_is_the_token_digest"] = record["receipt"]["files"]["output.txt"]["sha256"] == record["receipt"]["token_sha256"]
    for passed, container in ((False, written("result.json", None)), (True, honest)):
        out["cleanup_failure_passed_%s" % passed], _ = canary_case(
            fx, "cleanup-%s" % passed, M + "test_a_cleanup_failure_is_recorded_and_never_flips_the_verdict[passed=%s]" % passed,
            container, cleanup_refusal=True)
    out["failed_receipt_write_is_never_a_pass"], _ = canary_case(
        fx, "receipt-write", M + "test_a_failed_receipt_write_is_never_a_pass", honest, put_failure=True)
    # built from the source: the canary over the REAL `_check`, and the auth precondition
    out["real_check_honest"], _ = canary_case(fx, "real-check-honest", None, honest, real_check=True)
    out["real_check_docker_daemon_down"], _ = canary_case(
        fx, "real-check-daemon-down", None, honest, real_check=True, rc=1,
        extra={"note": "rc 1 from the docker run double; docker info answers 0 so the daemon is up"})
    world = fx.world("auth-missing", service="namespace", auth=False)
    out["auth_missing_refuses_before_anything"] = {
        "result": world.attempt(lambda: world.runner.file_canary("img")), "calls": world.view()}
    return out


# ---- check binding ------------------------------------------------------------------------------------------------
def gitc(root, *args):
    done = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise RuntimeError("fixture git failed: " + done.stderr[-300:])
    return done.stdout.strip()


def repository(base: Path) -> Path:
    """M7 test_git_workspace.py::repository (LABELLED), under the pinned git identity."""
    root = base / "repository"
    root.mkdir()
    gitc(root, "init", "-b", "main")
    gitc(root, "config", "user.name", "Fixture")
    gitc(root, "config", "user.email", "fixture@localhost")
    (root / "original.txt").write_text("original", encoding="utf-8")
    gitc(root, "add", ".")
    gitc(root, "commit", "-m", "Initial fixture")
    return root


def real_git_world(fx, name, *, candidate=False):
    api = fx.api
    world = fx.world(name)
    root = repository(world.dir)
    adapter = api.GitWorkspace(str(root), str(world.dir / "workspaces"))
    world.git, world.root = adapter, root
    world.runner.git = adapter
    if candidate:  # M7 test_release_recovery.py::candidate_runner
        workspace = adapter.prepare("candidate-task")
        (Path(workspace["path"]) / "change.txt").write_text("candidate", encoding="utf-8")
        record = adapter.capture(workspace)
        release = world.release(record, {"checks": ["tests"]})
        world.verify(release)
        with world.store.transaction() as tx:
            tx.put("images", release["id"], {"image": "sha256:fixture"})
        world.release_record = release
    world.before = world.rows()
    return world


def group_check_binding(fx):
    out, api, M = {}, fx.api, "tests/test_check_binding.py::"
    # 1. pytest summaries and the pure binding
    summaries = {
        "passed_skipped": api.pytest_summary("....\n5 passed, 2 skipped in 1.02s\n"),
        "failed_passed_warnings": api.pytest_summary("=== 1 failed, 4 passed, 3 warnings in 0.5s ==="),
        "errors": api.pytest_summary("2 errors in 0.1s"),
        "no_tests_ran": api.pytest_summary("no tests ran in 0.01s"),
        "traceback": api.pytest_summary("Traceback ...\nModuleNotFoundError: x")}
    classified = {
        "passed_skipped": api.classify_test_run(0, "5 passed, 2 skipped in 1.0s"),
        "all_skipped": api.classify_test_run(0, "3 skipped in 0.2s"),
        "no_tests_ran_rc5": api.classify_test_run(5, "no tests ran in 0.01s"),
        "deselected": api.classify_test_run(0, "2 deselected in 0.1s"),
        "failed": api.classify_test_run(1, "1 failed, 4 passed in 0.5s"),
        "liar_rc0": api.classify_test_run(0, "1 failed, 4 passed in 0.5s"),
        "unstructured": api.classify_test_run(0, "ok\n"), "xfailed": api.classify_test_run(0, "2 xfailed, 1 passed in 0.1s")}
    world = fx.world("summaries")
    out["pytest_summaries_are_parsed_and_only_executed_passes_count"] = {
        "mirrors": M + "test_pytest_summaries_are_parsed_and_only_executed_passes_count",
        "summaries": summaries, "classified": classified,
        "non_int_exit": world.attempt(lambda: api.classify_test_run("0", "1 passed")),
        "is_test_run": {"python_pytest": api.is_test_run([PY, "-m", "pytest", "-q"]), "uv_run_pytest": api.is_test_run(
            ["uv", "run", "pytest"]), "uv_sync": api.is_test_run(["uv", "sync"])},
        "outcomes": sorted(api.OUTCOMES),
        "bind_revision": {"equal_clean": api.bind_revision("a" * 40, "a" * 40, False),
                          "other_head": api.bind_revision("a" * 40, "b" * 40, False),
                          "dirty": api.bind_revision("a" * 40, "a" * 40, True),
                          "no_expected": api.bind_revision(None, "a" * 40, False)}}
    # 2. the binding over a real git worktree, the child answered by the process double
    world = real_git_world(fx, "binding")
    head = world.git._git("rev-parse", "HEAD")
    workspace = world.git.review_workspace(head, "binding-fixture")
    argv = [PY, "-c", "import sys; sys.exit(0)"]
    cases = {}
    with world.active(other=ok()):
        def project(result):
            return {"result": world.n(result), "receipt": world.n(world.artifacts.document(result["evidence"]))}

        cases["bound"] = project(world.runner._check(argv, workspace, expected_revision=head))
        cases["other_revision"] = project(world.runner._check(argv, workspace, expected_revision="f" * 40))
        (Path(workspace) / "scratch.txt").write_text("dirty", encoding="utf-8")
        cases["dirty_workspace"] = project(world.runner._check(argv, workspace, expected_revision=head))
        (Path(workspace) / "scratch.txt").unlink()
        plain = world.dir / "plain"
        plain.mkdir()
        cases["not_a_git_worktree"] = project(world.runner._check(argv, str(plain), expected_revision=head))
        cases["legacy_without_expected_revision"] = project(world.runner._check(argv, workspace))
    out["checks_bind_to_the_candidate_revision_of_the_workspace_they_ran_in"] = {
        "mirrors": M + "test_checks_bind_to_the_candidate_revision_of_the_workspace_they_ran_in",
        "head": head, "cases": cases, "calls": world.view()}
    # 3. the denominator: only the real suite computes it, and that needs real pytest children
    out["test_checks_pass_only_by_their_denominator_in_the_bound_workspace"] = {
        "mirrors": M + "test_test_checks_pass_only_by_their_denominator_in_the_bound_workspace",
        "unreachable": "ReleaseSuite runs real collected pytest children (run_logged_process, not the process double); "
                       "the reference environment is the SOURCE wheel, which carries no pytest, and the receipts hold "
                       "timings; the denominator rules themselves are recorded in the summaries case"}
    # 4. the isolation failure
    world = real_git_world(fx, "isolation", candidate=True)
    record = world.release_record
    with world.store.transaction() as tx:
        body = tx.get("releases", record["id"])
        body.update(status="reviewed", checks={})
        tx.put("releases", record["id"], body)
    world.before = world.rows()
    installs = []

    def fake_check(argv, cwd=None, timeout=None, env=None, expected_revision=None):
        installs.append([Path(argv[0]).name, *argv[1:2]])  # the install argv, whichever `uv` was resolved
        return {"passed": True, "evidence": "fixture:install", "outcome": "executed", "binding": {}}

    class Unavailable:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            raise api.ContractError("Explicit isolation failure fixture: compose unavailable")

        def __exit__(self, *args):
            pass

    world.runner._check = fake_check
    restore = api.install_seam("VerificationServices", Unavailable)
    try:
        result = world.attempt(lambda: world.runner.run(record["id"]))
    finally:
        restore()
    with world.store.transaction() as tx:
        current = tx.get("releases", record["id"])
    out["isolation_failure_stops_the_runner_before_any_test_check"] = {
        "mirrors": M + "test_isolation_failure_stops_the_runner_before_any_test_check", "result": result,
        "checks_run": installs, "release_status": current["status"], "release_checks": current["checks"],
        "evidence_stage": next((json.loads(e["body"])["stage"] for e in world.written if e["source"] == "canary-failure"), None),
        **world.finish()}
    # 5. the services are entered once and always exited
    for body in ("returns", "raises"):
        world = real_git_world(fx, "services-" + body, candidate=True)
        record = world.release_record
        with world.store.transaction() as tx:
            current = tx.get("releases", record["id"])
            current.update(status="reviewed", checks={})
            tx.put("releases", record["id"], current)
        world.before = world.rows()
        events = []

        class Counting:
            def __init__(self, directory, artifacts):
                events.append(["init", directory.name])

            def __enter__(self):
                events.append(["enter"])
                if events.count(["enter"]) != 1:
                    raise AssertionError("entered twice")
                return {"database_url": "postgresql://fixture/isolated", "redis_url": "redis://fixture/0"}

            def __exit__(self, kind, value, tb):
                events.append(["exit", kind.__name__ if kind else None])
                return False

        def fake_check(argv, cwd=None, timeout=None, env=None, expected_revision=None, body=body):
            if Path(argv[0]).name == "uv" and argv[1:2] == ["sync"]:  # bare or absolute `uv` (deployment.uv_command)
                return {"passed": True, "evidence": "fixture:install", "outcome": "executed", "binding": {}}
            if body == "raises":
                raise RuntimeError("fixture: test runner exploded inside the services context")
            return {"passed": False, "evidence": "fixture:tests", "outcome": "executed", "reason": "fixture failure",
                    "binding": {}}

        world.runner._check = fake_check
        restore = api.install_seam("VerificationServices", Counting)
        try:
            result = world.attempt(lambda: world.runner.run(record["id"]))
        finally:
            restore()
        out["verification_services_entered_once_and_always_exited_" + body] = {
            "mirrors": M + "test_verification_services_are_entered_once_and_always_exited[%s]" % body,
            "result": result, "events": events, "entered_once": events.count(["enter"]) == 1, **world.finish()}
    # 6. the timeout receipt keeps the binding
    world = real_git_world(fx, "timeout")
    head = world.git._git("rev-parse", "HEAD")
    workspace = world.git.review_workspace(head, "timeout-fixture")
    argv = [PY, "-c", "import time; time.sleep(30)"]
    with world.active(other=subprocess.TimeoutExpired(argv, 1)):
        result = world.runner._check(argv, workspace, timeout=1, expected_revision=head)
    receipt = world.artifacts.document(result["evidence"])
    out["timeout_receipt_keeps_the_binding"] = {
        "mirrors": M + "test_timeout_receipt_keeps_the_binding", "result": world.n(result),
        "receipt": world.n(receipt), "observed_head_is_the_candidate": receipt["binding"]["observed_head"] == head,
        "timed_out_in_error": "timed out" in receipt["error"], "calls": world.view()}
    return out


# ---- abandon ------------------------------------------------------------------------------------------------------
def abandon_world(fx, name, *, intent=None, lock=None, queue=None, ancestor=False, verified=True, status="prepared"):
    world = fx.world(name)
    world.git = FixtureGit(fx, world.dir, ancestor=ancestor)
    world.runner.git = world.git
    record = reviewed(world, verified=verified)
    with world.store.transaction() as tx:
        tx.put("promotion_intents", record["id"], {
            "id": record["id"], "candidate_hash": world.api.digest(record["candidate"]), "image": IMAGE_ID,
            "candidate": record["candidate"], "expected_active": None, "status": status, "remote": None,
            "at": "2026-01-01T00:00:00+00:00", **(intent or {})})
        if lock is not None:
            tx.put("deployment_locks", "controller", lock)
        if queue is not None:
            tx.put("release_queue", record["id"], {"id": record["id"], "status": queue})
    world.before = world.rows()
    world.record = record
    return world


def group_abandon(fx):
    out = {}

    def run(name, reason="operator abandons", **kw):
        world = abandon_world(fx, name, **kw)
        result = world.attempt(lambda: world.runner.abandon(world.record["id"], reason))
        return {"result": result, **world.finish()}

    out["prepared_without_a_queue_row"] = run("prepared")
    out["prepared_with_a_claimed_queue_row"] = run("prepared-queue", queue="claimed")
    out["prepared_with_a_reviewed_release"] = run("prepared-reviewed", verified=False)
    out["expired_controller_lease"] = run("lock-expired", lock={"lease_until": "2025-01-01T00:00:00+00:00"})
    out["controller_lock_without_a_lease"] = run("lock-no-lease", lock={"owner": "controller"})
    out["controller_still_running"] = run("lock-running", lock={"lease_until": "2099-01-01T00:00:00+00:00"})
    out["external_started"] = run("external", intent={"external_started": True})
    out["merge_recorded"] = run("merge", intent={"merge": {"merged": True, "revision": REV_CAND}})
    out["candidate_already_in_main"] = run("ancestor", ancestor=True)
    out["intent_already_abandoned"] = run("abandoned", status="abandoned")
    out["intent_completed"] = run("completed", status="completed")
    out["intent_merged"] = run("merged-status", status="merged")
    out["blank_reason"] = run("blank", reason="   ")
    out["non_text_reason"] = run("non-text", reason=None)
    world = fx.world("abandon-no-intent")
    world.git = FixtureGit(fx, world.dir)
    world.runner.git = world.git
    out["no_promotion_intent"] = {"result": world.attempt(lambda: world.runner.abandon("missing", "reason")), **world.finish()}
    world = abandon_world(fx, "abandon-release-missing")
    with world.store.transaction() as tx:
        tx.put("promotion_intents", "ghost", {"id": "ghost", "status": "prepared", "candidate": {"revision": REV_CAND}})
    world.before = world.rows()
    out["intent_without_a_release"] = {"result": world.attempt(lambda: world.runner.abandon("ghost", "reason")),
                                       **world.finish()}
    return out


# ---- monitor ------------------------------------------------------------------------------------------------------
SERVICES = ("conductor", "improvement-lead", "unmonitored-service")
RID, PREVIOUS = "release-active", "release-previous"


def monitor_world(fx, name, *, image=True, active=True, previous=False, failures=None, **overrides):
    world = fx.world(name)
    world.git = FixtureGit(fx, world.dir)
    world.runner.git = world.git
    with world.store.transaction() as tx:
        if active:
            tx.put("deployment", "active", {"release_id": RID, "revision": REV_CAND,
                                            "previous": {"release_id": PREVIOUS} if previous else None,
                                            "at": "2026-01-01T00:00:00+00:00"})
            tx.put("releases", RID, {"id": RID, "candidate": release_candidate(), "status": "active"})
            if previous:
                tx.put("releases", PREVIOUS, {"id": PREVIOUS, "candidate": release_candidate(), "status": "superseded"})
                tx.put("deployment_history", PREVIOUS, {"release_id": PREVIOUS, "revision": REV_BASE, "previous": None})
            if image:
                tx.put("images", RID, {"id": RID, "image": IMAGE_ID, "revision": REV_CAND})
            if failures is not None:
                tx.put("health_probes", RID + ":image", {"id": RID + ":image", "failures": failures,
                                                          "at": "2026-01-01T00:00:00+00:00", "check": {}})
    world.before = world.rows()
    rows = "\n".join(json.dumps({"ID": "id-" + s, "Service": s}) for s in SERVICES) + "\nnot-json-noise"
    world.defaults = {"compose_ps": ok(rows), **overrides}
    return world


def monitor_case(fx, name, **kw):
    overrides = {k: kw.pop(k) for k in list(kw) if k in DEFAULTS}
    world = monitor_world(fx, name, **kw)
    with world.active(**{**world.defaults, **overrides}):
        result = world.attempt(world.runner.monitor)
    return {"result": result, **world.finish()}


def group_monitor(fx):
    out = {}
    out["no_deployment"] = monitor_case(fx, "no-deployment", active=False)
    out["active_without_an_image_receipt"] = monitor_case(fx, "no-image", image=False)
    out["matching_image_is_healthy"] = monitor_case(fx, "healthy")
    out["drifted_image_is_degraded"] = monitor_case(fx, "drift", container_inspect=ok(OTHER_IMAGE + "\n"))
    out["image_start_fails_unhealthy_first_failure"] = monitor_case(fx, "unhealthy", start=(1, "", "codex: not found"))
    out["image_start_fails_below_threshold_with_a_previous"] = monitor_case(fx, "unhealthy-previous", previous=True,
                                                                              start=(1, "", "codex: not found"))
    out["image_start_fails_at_the_threshold_rolls_back"] = monitor_case(
        fx, "unhealthy-rollback", previous=True, failures=2, start=(1, "", "codex: not found"))
    out["docker_cli_unavailable"] = monitor_case(fx, "cli-missing", start=FileNotFoundError("docker"))
    out["docker_daemon_down_is_unknown_and_keeps_the_count"] = monitor_case(fx, "daemon-down", failures=1, start=DAEMON_DOWN)
    out["docker_info_fails_after_a_failed_start_is_unknown"] = monitor_case(
        fx, "info-fails", start=(1, "", "odd"), info=(1, "", "down"))
    out["container_listing_unavailable"] = monitor_case(fx, "listing-rc", compose_ps=(1, "", "no project"))
    out["container_listing_os_error"] = monitor_case(fx, "listing-oserror", compose_ps=OSError("fixture: no docker"))
    out["container_listing_times_out"] = monitor_case(
        fx, "listing-timeout", compose_ps=subprocess.TimeoutExpired(["docker", "compose", "ps"], 30))
    out["expected_image_unavailable"] = monitor_case(fx, "image-gone", image_inspect=(1, "", "no such image"))
    out["expected_image_empty_output"] = monitor_case(fx, "image-empty", image_inspect=ok("\n"))
    out["container_inspection_unavailable"] = monitor_case(fx, "inspect-rc", container_inspect=(1, "", "gone"))
    out["container_exec_fails_unhealthy"] = monitor_case(fx, "exec-fails", exec=(1, "", "exec failed"))
    out["container_exec_unavailable_is_unknown"] = monitor_case(fx, "exec-down", exec=DAEMON_DOWN)
    out["malformed_container_row_is_unavailable"] = monitor_case(
        fx, "row-key", compose_ps=ok(json.dumps({"Service": "conductor"})))
    out["no_running_containers_is_healthy"] = monitor_case(fx, "idle", compose_ps=ok(""))
    return out


# ---- pin ---------------------------------------------------------------------------------------------------------
def pin_git(fx, world, *, paths=("tests/test_fix.py",), parent=REV_BASE, tree="7" * 40, diff="evaluator diff",
            revision=REV_EVAL, failing=False):
    def fail(r, b):
        raise RuntimeError("fixture: git failed")

    return FixtureGit(fx, world.dir, parents={revision: parent}, inspect=fail if failing else lambda r, b: {
        "revision": revision if r == REV_EVAL else r, "base": b, "tree": tree, "diff": diff, "files": list(paths)})


def group_pin(fx):
    out, api = {}, fx.api
    world = fx.world("pin-resolve")
    git = pin_git(fx, world)
    resolved = api.resolve_evaluator_pin(git, REV_EVAL, REV_BASE)
    out["resolve_evaluator_pin"] = {"result": resolved, "git_calls": git.calls,
                                    "patch_sha256_is_the_diff_digest": resolved["patch_sha256"] == hashlib.sha256(
                                        b"evaluator diff").hexdigest(),
                                    "evaluator_patch_sha256_empty": api.evaluator_patch_sha256("")}
    # _test_source: the ordinary release, the migration, and each refusal
    candidate = release_candidate()

    def source_case(name, mutate=None, *, source=REV_EVAL, git_kwargs=None, candidate_revision=None, migration=True):
        world = fx.world("pin-" + name)
        git = pin_git(fx, world, **(git_kwargs or {}))
        world.git = git
        world.runner.git = git
        pin = dict(resolved) if migration else None
        if mutate and pin is not None:
            mutate(pin)
        release = {"id": "pin", "candidate": dict(candidate), "policy": {"checks": CHECKS, "revision": source}}
        if pin is not None:
            release["evaluator_migration"] = pin
        result = world.attempt(lambda: world.runner._test_source(release, candidate_revision))
        return {"result": result, "git_calls": git.calls}

    out["ordinary_release_uses_the_base"] = source_case("ordinary", source=REV_BASE, migration=False)
    out["ordinary_release_without_a_revision_key"] = {
        "result": world.attempt(lambda: world.runner._test_source(
            {"id": "pin", "candidate": dict(candidate), "policy": {"checks": CHECKS}}, None))}
    out["migrated_release_uses_the_evaluator"] = source_case("migrated")
    out["no_migration_names_the_source"] = source_case("no-migration", migration=False)
    out["migration_names_another_evaluator"] = source_case("other-evaluator", lambda p: p.update(evaluator_revision="9" * 40))
    out["migration_names_another_base"] = source_case("other-base", lambda p: p.update(base="8" * 40))
    out["evaluator_is_the_candidate"] = source_case("is-candidate", source=REV_CAND, git_kwargs={"revision": REV_CAND},
                                                    mutate=lambda p: p.update(evaluator_revision=REV_CAND))
    out["evaluator_is_the_inspected_candidate_revision"] = source_case("is-inspected", candidate_revision=REV_EVAL)
    out["evaluator_revision_resolves_elsewhere"] = source_case("resolves-elsewhere", git_kwargs={"revision": "6" * 40})
    out["evaluator_parent_is_not_the_base"] = source_case("parent", git_kwargs={"parent": "5" * 40})
    out["evaluator_tree_differs"] = source_case("tree", lambda p: p.update(evaluator_tree="4" * 40))
    out["evaluator_paths_differ"] = source_case("paths-differ", lambda p: p.update(paths=["tests/other.py"]))
    out["evaluator_paths_outside_tests"] = source_case(
        "paths-outside", lambda p: p.update(paths=["src/x.py"]), git_kwargs={"paths": ("src/x.py",)})
    out["evaluator_paths_empty"] = source_case("paths-empty", lambda p: p.update(paths=[]), git_kwargs={"paths": ()})
    out["evaluator_patch_differs"] = source_case("patch", lambda p: p.update(patch_sha256="3" * 64))
    out["evaluator_git_failure_propagates"] = source_case("git-failure", git_kwargs={"failing": True})
    # the controller code (INV-RELEASE-ENVIRONMENT-REVERIFY-001)
    CTRL = "7" * 40

    def controller_case(name, record, running, *, present=True):
        world = fx.world("controller-" + name)
        release = {"id": "controller", "candidate": dict(candidate), "policy": {"checks": CHECKS}}
        if present:
            release["environment_reverification"] = record
        restore = api.install_seam("controller_code_revision", lambda: running)
        try:
            return {"result": world.attempt(lambda: api.ReleaseRunner._require_controller_code(release))}
        finally:
            restore()

    out["controller_no_reverification_record"] = controller_case("absent", None, None, present=False)
    out["controller_record_is_not_a_dict"] = controller_case("not-dict", "text", CTRL)
    out["controller_revision_missing"] = controller_case("missing", {}, CTRL)
    out["controller_revision_not_hex"] = controller_case("not-hex", {"controller_revision": "NOT-A-REVISION"}, CTRL)
    out["controller_revision_short"] = controller_case("short", {"controller_revision": "7" * 39}, CTRL)
    out["controller_revision_not_text"] = controller_case("not-text", {"controller_revision": 7}, CTRL)
    out["controller_running_revision_unknown"] = controller_case("unknown", {"controller_revision": CTRL}, None)
    out["controller_running_revision_differs"] = controller_case("differs", {"controller_revision": CTRL}, "8" * 40)
    out["controller_running_revision_equal"] = controller_case("equal", {"controller_revision": CTRL}, CTRL)
    # through evaluate: the refusal comes before any workspace, check or container
    world = fx.world("controller-through-evaluate")
    world.git = FixtureGit(fx, world.dir)
    world.runner.git = world.git
    record = reviewed(world)
    with world.store.transaction() as tx:
        body = tx.get("releases", record["id"])
        body["environment_reverification"] = {"controller_revision": CTRL}
        tx.put("releases", record["id"], body)
    world.before = world.rows()
    restore = api.install_seam("controller_code_revision", lambda: "8" * 40)
    try:
        with world.active():
            world.suite_double()
            result = world.attempt(lambda: world.runner.evaluate(record["id"]))
    finally:
        restore()
    out["controller_refusal_precedes_every_workspace_and_process"] = {"result": result, **world.finish()}
    # through evaluate: the evaluator pin decides the incumbent workspace
    world = fx.world("pin-through-evaluate")
    world.git = pin_git(fx, world, revision=REV_EVAL)
    world.runner.git = world.git
    candidate_row = release_candidate(diff_hash=api.digest(DIFF))
    world.git.inspected = lambda r, b: {"revision": REV_EVAL if r == REV_EVAL else r, "base": b, "tree": TREE if r != REV_EVAL else "7" * 40,
                                        "diff": "evaluator diff", "files": ["tests/test_fix.py"]}
    resolved_here = api.resolve_evaluator_pin(world.git, REV_EVAL, REV_BASE)
    world.git.calls.clear()
    record = world.release(candidate_row, {"checks": CHECKS, "revision": REV_EVAL})
    with world.store.transaction() as tx:
        body = tx.get("releases", record["id"])
        body["evaluator_migration"] = resolved_here
        tx.put("releases", record["id"], body)
    world.before = world.rows()
    world.git.inspected = lambda r, b: {"revision": r, "base": b, "tree": TREE if r == REV_CAND else "7" * 40,
                                        "diff": "evaluator diff" if r == REV_EVAL else DIFF,
                                        "files": ["tests/test_fix.py"] if r == REV_EVAL else ["src/change.py"]}
    with world.active(install=(1, "", "stop after the install")):
        world.suite_double()
        result = world.attempt(lambda: world.runner.evaluate(record["id"]))
    out["evaluate_runs_the_incumbent_tests_of_the_pinned_evaluator"] = {"result": result, **world.finish()}
    # the attempt resources and the named refusals
    world = fx.world("attempt-resources")
    out["attempt_resources"] = {
        "valid": world.attempt(lambda: api.attempt_resources(ATTEMPT)),
        "upper_case": world.attempt(lambda: api.attempt_resources(ATTEMPT.upper())),
        "short": world.attempt(lambda: api.attempt_resources("abc")),
        "not_text": world.attempt(lambda: api.attempt_resources(None))}
    out["named_refusals"] = {
        "pin_mismatch": {"base": "ContractError" if issubclass(api.EvaluatorPinMismatch, api.ContractError) else None,
                         "reason_code": api.EvaluatorPinMismatch.reason_code},
        "code_mismatch": {"base": "ContractError" if issubclass(api.EvaluatorCodeMismatch, api.ContractError) else None,
                          "reason_code": api.EvaluatorCodeMismatch.reason_code}}
    out["uv_command"] = {"executable_name": Path(api.uv_command()).name}
    return out


GROUPS = (("stages", group_stages), ("drift", group_drift), ("rebase", group_rebase), ("file_canary", group_file_canary),
          ("check_binding", group_check_binding), ("abandon", group_abandon), ("monitor", group_monitor),
          ("pin", group_pin))


def count_calls(value) -> int:
    if isinstance(value, dict):
        return sum(len(v) if k == "calls" and isinstance(v, list) else count_calls(v) for k, v in value.items())
    if isinstance(value, list):
        return sum(count_calls(v) for v in value)
    return 0


def run(api) -> dict:
    result, counts, processes = {}, {}, {}
    saved = {key: os.environ.get(key) for key in GIT_PINNED}
    os.environ.update(GIT_PINNED)
    try:
        with tempfile.TemporaryDirectory(prefix="s7-release-runner-") as raw:
            fx = Fx(api, Path(raw).resolve())
            for name, group in GROUPS:
                result[name] = group(fx)
                counts[name] = len(result[name])
                processes[name] = count_calls(result[name])
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    result["cases_per_group"] = counts
    result["process_calls_per_group"] = processes
    return result

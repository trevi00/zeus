"""The release runner: the host-side canary controller, the file canary, the check binding and the evaluator stages (INV-CHECK-001, INV-RELEASE-FILE-CANARY-001, INV-HOST-DELIVERY-VERIFY-001).

Layer: adapters
Context: delivery
Owns: `ReleaseRunner`, the file canary, `attempt_resources`, the evaluator pin and the controller code refusals (M7 `adapters/deployment.py`)
Does not own: the release rows (review.application.releases, injected as `releases`), the ticket binding (intake, injected), process creation (host_os, injected as `runner`), the release suite and the verification services (S8, injected), the native hooks (S10, injected), the rebase request (S5, injected), the container names (execution, injected as `naming`), the release and queue rows (review, injected as `releases` and `release_queue`), the Compose environment (composition.configuration, injected)
Entry points: ReleaseRunner, attempt_resources, canary_handoff_script, inspect_canary_file, canary_postcondition, evaluator_patch_sha256, resolve_evaluator_pin, uv_command, controller_code_revision
Contracts: INV-CHECK-001, INV-CHECK-002, INV-RELEASE-FILE-CANARY-001, INV-RELEASE-EVALUATOR-MIGRATION-001, INV-RELEASE-ENVIRONMENT-REVERIFY-001, INV-HOST-DELIVERY-VERIFY-001, INV-RELEASE-001

S7 named transcription of M7 `adapters/deployment.py` (SOURCE e38aa722) through the declared rules (DESIGN-s7 adapters-move §13, A/evidence/rebuild/s7/deployment-move/transcribe.py): V6 injection of every cross-context collaborator, the injected clock, `attempt_resources(..., naming=)` and the import homes; every body is otherwise M7's.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import canonical, digest, utcnow
from codex_harness.kernel.policy import POLICY
from codex_harness.review.domain.check_results import bind_revision, is_test_run

# INV-HOST-DELIVERY-VERIFY-001: the two containers one owned verification attempt may start. Their
# names are the ones `OwnedContainer` computes for these roles, so creation and reconciliation use
# one exact name and one exact label pair and never a prefix.
ROLE_START, ROLE_CANARY = "release-start", "release-canary"
ATTEMPT_ID = re.compile(r"^[0-9a-f]{32}$")
# The observation-error codes an owned evaluation answers with instead of a verdict.
RETRY_OBSERVATION = "verification_observation_unavailable"
RETRY_ISOLATION = "verification_isolation_unavailable"
RETRY_AUTH = "verification_auth_unavailable"
RETRY_WORKSPACE = "verification_workspace_unavailable"


class EvaluatorPinMismatch(ContractError):
    """INV-RELEASE-EVALUATOR-MIGRATION-001: git disagrees with the recorded evaluator pin.

    A named refusal, never an observation error: the verifier records it as `refused`, not retry.
    """

    reason_code = "evaluator_pin_mismatch"


class EvaluatorCodeMismatch(ContractError):
    """INV-RELEASE-ENVIRONMENT-REVERIFY-001: this controller is not the code the release names.

    An environment re-verification is evaluated only by controller code at exactly the recorded
    `controller_revision`; an unknown or different running revision is this named refusal, raised
    before any workspace, check or container.
    """

    reason_code = "evaluator_code_mismatch"


def controller_code_revision() -> str | None:
    """The revision of the codex_harness package this process runs (runtime_revision SSOT)."""
    from codex_harness.delivery.adapters.host_delivery import runtime_revision

    try:
        # M7: Path(codex_harness.__file__).resolve().parents[2], the package's grandparent
        return runtime_revision(Path(__file__).resolve().parents[4])
    except Exception:  # unknown is refused by the caller, never assumed equal
        return None


# INV-RELEASE-FILE-CANARY-001: the two files the file canary's container writes and the host reads.
CANARY_FILES = ("result.json", "output.txt")


def canary_handoff_script(uid, gid) -> str:
    """The fixed /bin/sh wrapper: the unchanged codex argv, then a no-follow ownership handoff.

    The codex exit code is preserved; only the two fixed files are handed to the numeric controller
    uid:gid, `-h` so a symlink is never followed. Umask, credentials and modes are not changed.
    """
    require(type(uid) is int and type(gid) is int and uid >= 0 and gid >= 0,
            "Invalid controller uid/gid for the file canary handoff")
    targets = " ".join("/canary/" + name for name in CANARY_FILES)
    return f'codex "$@"; rc=$?; chown -h {uid}:{gid} {targets} 2>/dev/null; exit $rc'


def _controller_ids() -> tuple:
    getuid, getgid = getattr(os, "getuid", None), getattr(os, "getgid", None)
    require(getuid is not None and getgid is not None,
            "The file canary ownership handoff needs a POSIX controller uid/gid")
    return getuid(), getgid()


def _file_type(mode: int) -> str:
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISREG(mode):
        return "file"
    return "directory" if stat.S_ISDIR(mode) else "other"


def inspect_canary_file(path: Path, token: str) -> dict:
    """INV-RELEASE-FILE-CANARY-001: one file's sanitized observation and named outcome.

    lstat first (a symlink or directory is `not_regular`, never followed), then an O_NOFOLLOW read.
    The entry carries metadata and a digest only - never the bytes or the token.
    """
    entry = {"exists": False, "type": None, "mode": None, "uid": None, "gid": None, "size": None,
             "sha256": None, "read": None, "parse": None, "compare": None}
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {**entry, "outcome": "missing"}
    except OSError as exc:
        return {**entry, "read": "error:" + type(exc).__name__, "outcome": "unreadable:" + type(exc).__name__}
    entry.update(exists=True, type=_file_type(info.st_mode), mode=format(stat.S_IMODE(info.st_mode), "04o"),
                 uid=info.st_uid, gid=info.st_gid, size=info.st_size)
    if entry["type"] != "file":
        return {**entry, "outcome": "not_regular"}
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return {**entry, "outcome": "not_regular"}
            data = handle.read()
    except OSError as exc:
        return {**entry, "read": "error:" + type(exc).__name__, "outcome": "unreadable:" + type(exc).__name__}
    entry.update(read="ok", sha256=hashlib.sha256(data).hexdigest())
    if path.name == "output.txt":
        match = data == token.encode("utf-8")
        return {**entry, "compare": "match" if match else "mismatch", "outcome": "ok" if match else "bytes_mismatch"}
    try:
        answer = json.loads(data.decode("utf-8"))
    except ValueError:  # UnicodeDecodeError and JSONDecodeError are both ValueError
        return {**entry, "parse": "not_json", "outcome": "not_json"}
    if not isinstance(answer, dict):
        return {**entry, "parse": "not_object", "outcome": "not_object"}
    if "value" not in answer:
        return {**entry, "parse": "object", "compare": "no_value", "outcome": "no_value"}
    match = type(answer["value"]) is str and answer["value"] == token
    return {**entry, "parse": "object", "compare": "match" if match else "mismatch",
            "outcome": "ok" if match else "value_mismatch"}


def canary_postcondition(root: Path, token: str) -> dict:
    """Every fixed file's observation, and the first failing outcome in fixed order, else `ok`."""
    files = {name: inspect_canary_file(Path(root) / name, token) for name in CANARY_FILES}
    failing = [(name, entry["outcome"]) for name, entry in files.items() if entry["outcome"] != "ok"]
    return {"files": files, "reason": failing[0][1] if failing else "ok",
            "reason_file": failing[0][0] if failing else None,
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest()}


def _remove_canary_directory(directory: str) -> dict:
    """Remove the canary directory and record what is actually left; never raises."""
    error = None
    try:
        shutil.rmtree(directory)
    except Exception as exc:
        error = type(exc).__name__
    removed = not os.path.lexists(directory)
    return {"removed": removed} if error is None and removed else {"removed": removed, "error_type": error}


def evaluator_patch_sha256(diff: str) -> str:
    """The `patch_sha256` of an evaluator approval.

    SHA-256 over the UTF-8 bytes of `GitWorkspace.inspect(E, base)["diff"]`, i.e. the output of
    `git diff --no-ext-diff <base> <E> --` with trailing whitespace stripped by the adapter.
    """
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def resolve_evaluator_pin(git, evaluator_revision: str, base: str) -> dict:
    """The evaluator pin as the repository derives it (INV-RELEASE-EVALUATOR-MIGRATION-001).

    The one derivation shared by migration creation (before any write) and the runner's
    execution-time recheck: E and base resolved to commits, E's first parent, E's tree, the sorted
    changed paths and `patch_sha256` of `git diff <base> <E>`. Git failures propagate unchanged.
    """
    inspected = git.inspect(evaluator_revision, base)
    return {"evaluator_revision": inspected["revision"], "parent": git.parent(inspected["revision"]),
            "base": inspected["base"], "evaluator_tree": inspected["tree"],
            "paths": sorted(inspected["files"]), "patch_sha256": evaluator_patch_sha256(inspected["diff"])}


def attempt_resources(attempt_id: str, *, naming) -> dict:
    """The exact resources one verification attempt may create (INV-HOST-DELIVERY-VERIFY-001)."""
    require(isinstance(attempt_id, str) and bool(ATTEMPT_ID.fullmatch(attempt_id)),
            "Invalid verification attempt id")
    names = {role: naming.name(attempt_id, role) for role in (ROLE_START, ROLE_CANARY)}
    return {"attempt_id": attempt_id, "project": "zeus-verify-" + attempt_id, "containers": names,
            "labels": {role: naming.labels(attempt_id, role) for role in names}}


def uv_command() -> str:
    """The `uv` the evaluator installs a candidate with: `uv` itself whenever PATH has it (the legacy argv,
    unchanged), else the service user's standard install `~/.local/bin/uv`. The aibox controller unit's PATH is
    pinned to the release venv and the system directories (M1 `controller_env_exact`), and uv is installed there
    only for the user, as the host's release build pins it; an absent uv stays an observation error."""
    if shutil.which("uv"):
        return "uv"
    local = Path.home() / ".local" / "bin" / "uv"
    return str(local) if local.is_file() and os.access(local, os.X_OK) else "uv"


def _labels(owned, role) -> list:
    if owned is None:
        return []
    return ["--name", owned["containers"][role],
            *[part for label in owned["labels"][role] for part in ("--label", label)]]


class ReleaseRunner:
    """Host-side canary controller, independent of the candidate's Codex process."""

    def __init__(self, service, git, artifacts, auth: str, auto_merge: bool = True, fence=None,
                 verification_root=None, *, releases, ticket_binding, ticket_superseded, runner, release_suite,
                 verification_services, verification_environment, hooks, request_rebase, compose_environment,
                 naming, release_queue, clock=None):
        # V6 (DESIGN-s7 adapters-move §13): every collaborator another context owns is injected; composition
        # (`composition.release_verification.release_runner`) wires the defaults M7 constructed here.
        self.service, self.git, self.artifacts = service, git, artifacts
        self.auth = Path(auth).resolve()
        self.auto_merge = auto_merge
        self.releases = releases
        self.fence = fence or (lambda: None)
        self.verification_root = verification_root
        self.ticket_binding, self.ticket_superseded, self.runner = ticket_binding, ticket_superseded, runner
        self.release_suite, self.verification_services = release_suite, verification_services
        self.verification_environment, self.hooks = verification_environment, hooks
        self.request_rebase, self.compose_environment = request_rebase, compose_environment
        self.naming, self.release_queue, self.clock = naming, release_queue, clock

    def _observe_workspace(self, cwd):
        """What the check will actually run against: HEAD and cleanliness of the cwd, read from Git."""
        try:
            head = self.git._git("rev-parse", "HEAD", cwd=cwd)
            dirty = bool(self.git._git("status", "--porcelain", cwd=cwd))
        except Exception as exc:  # not a Git worktree, or Git failed: recorded, never assumed clean
            return {"observed_head": None, "dirty": None, "error": type(exc).__name__ + ": " + str(exc)[:200]}
        return {"observed_head": head, "dirty": dirty, "error": None}

    def _check(self, argv: list[str], cwd: str | None = None,
               timeout: int = POLICY.release_check_seconds, env=None, expected_revision: str | None = None) -> dict:
        self.fence()
        # INV-CHECK-001: the receipt names the tree the check ran against, not only the argv.
        binding = {"cwd": str(Path(cwd).resolve()) if cwd else None, "expected_revision": expected_revision,
                   "env_keys": sorted(env) if isinstance(env, dict) else None}
        if cwd is not None and expected_revision is not None:
            observed = self._observe_workspace(cwd)
            binding.update(observed)
            if observed["error"] is not None:
                # The tree could not be observed: an observation error, not a verdict about the candidate.
                receipt = self.artifacts.put(canonical({"argv": argv, "binding": binding, "executed": False}), "canary-failure")
                return {"passed": False, "evidence": receipt["ref"], "outcome": "observation_error",
                        "reason": "workspace revision could not be observed: " + observed["error"], "binding": binding}
            binding.update(bind_revision(expected_revision, observed["observed_head"], observed["dirty"]))
            if not binding["bound"]:
                receipt = self.artifacts.put(canonical({"argv": argv, "binding": binding, "executed": False}), "canary")
                return {"passed": False, "evidence": receipt["ref"], "outcome": "revision_mismatch",
                        "reason": binding["reason"], "binding": binding}
        if is_test_run(argv):
            # INV-CHECK-002: a release test suite is an exact collected manifest run in bounded
            # serial batches; `timeout` bounds each owned process, not the whole suite.
            return self.release_suite(self.artifacts, self.fence).check(argv, cwd=cwd, timeout=timeout,
                                                                 env=env, binding=binding)
        try:
            process = self.runner(argv, cwd=cwd, timeout=timeout, env=env)
            self.fence()
            verdict = {"passed": process.returncode == 0, "outcome": "executed"}
            receipt = self.artifacts.put(canonical({"argv": argv, "exit_code": process.returncode,
                                         "stdout": process.stdout, "stderr": process.stderr,
                                         "binding": binding, "verdict": verdict}), "canary")
            unavailable = argv[0] == "docker" and any(text in process.stderr.lower() for text in (
                    "cannot connect to the docker daemon", "is the docker daemon running",
                    "error during connect", "failed to connect to the docker"))
            if argv[0] == "docker" and process.returncode and not unavailable:
                # Localized daemon diagnostics are not candidate execution evidence.
                server = self.runner(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15)
                unavailable = server.returncode != 0
            return {"passed": verdict["passed"] and not unavailable, "evidence": receipt["ref"],
                    "outcome": "observation_error" if unavailable else verdict["outcome"],
                    "binding": binding}
        except (subprocess.TimeoutExpired, OSError) as exc:
            receipt = self.artifacts.put(canonical({"argv": argv, "binding": binding, "error": str(exc)}), "canary-failure")
            return {"passed": False, "evidence": receipt["ref"], "outcome": "observation_error", "binding": binding}

    def run(self, release_id: str) -> dict:
        self.fence()
        # The queue coordinator alone owns claim/completion state.
        try:
            return self._run(release_id)
        except self.ticket_superseded as exc:
            self.fence()
            with self.service.store.transaction() as tx:
                self.releases.record_superseded(release_id, str(exc), transaction=tx)
            return {"status": "superseded_by_ticket_revision", "reason": str(exc)}

    def _rejection_checks(self, release, completed, failed) -> dict:
        # INV-RELEASE-001: skipped checks are explicitly unexecuted, never synthetic passes.
        receipt = self.artifacts.put(canonical({"status": "not_run",
            "reason": "prerequisite_failed", "prerequisite_ref": failed["evidence"]}),
            "canary-skipped")
        return {name: completed.get(name, {"passed": False, "skipped": True,
                                           "evidence": receipt["ref"]})
                for name in release["policy"]["checks"]}

    def _stop(self, release, completed, failed, receipt, reason_code=RETRY_OBSERVATION) -> dict:
        """The evaluation ends at a failed check: an observation error is a retry, never a verdict."""
        if failed.get("outcome") == "observation_error":
            return {"verdict": "retry", "reason_code": reason_code, "evidence": failed["evidence"],
                    "checks": completed, "receipt": receipt}
        return {"verdict": "checked", "passed": False, "image": None,
                "checks": self._rejection_checks(release, completed, failed), "receipt": receipt}

    def evaluate(self, release_id: str, *, attempt: str | None = None) -> dict:
        """E1 of INV-HOST-DELIVERY-VERIFY-001: the incumbent checks of one reviewed release.

        The same steps, in the same order, as the legacy runner, and it WRITES NOTHING TO THE STORE:
        it is not pure either - it builds images and runs containers - so it returns a receipt of
        the external results it produced next to one of `checked` (every policy check, skipped ones
        explicitly `not_run`) or `retry` (an observation error, with its code). `attempt` names the
        owned attempt whose exact compose project and container names are used; None keeps the
        legacy random names. Cancellation and a lost fence propagate as exceptions.
        """
        with self.service.store.transaction() as tx:
            release = tx.get("releases", release_id)
            require(release is not None, "Release not found")
            require(release["status"] == "reviewed", "Release not reviewed")
            self.ticket_binding(tx, release["candidate"])
        return self._evaluate(release, None if attempt is None else attempt_resources(attempt, naming=self.naming))

    def _evaluate(self, release, owned) -> dict:
        self._require_controller_code(release)
        release_id, candidate = release["id"], release["candidate"]
        receipt = {"release_id": release_id, "revision": candidate["revision"],
                   "attempt_id": None if owned is None else owned["attempt_id"],
                   "project": None if owned is None else owned["project"],
                   "containers": {} if owned is None else dict(owned["containers"]),
                   "workspaces": {}, "image": None}
        if owned is not None and not self.auth.is_file():
            # Presence only, before any work; the file is never opened here.
            receipt_ref = self.artifacts.put(canonical({"stage": "verification_auth", "present": False}),
                                             "canary-failure")["ref"]
            return {"verdict": "retry", "reason_code": RETRY_AUTH, "evidence": receipt_ref, "checks": {},
                    "receipt": receipt}
        inspected = self.git.inspect(candidate["revision"], candidate["base"])
        require(inspected["tree"] == candidate["tree"], "Candidate tree mismatch")
        # FA-015: the reviewed patch and target repository are re-derived, never trusted from the record.
        if candidate.get("diff_hash"):
            require(digest(inspected["diff"]) == candidate["diff_hash"], "Candidate patch mismatch")
        if candidate.get("repository") is not None:
            require(candidate["repository"] == self.git.target_identity(),
                    "Candidate target repository changed since review")
        test_source = self._test_source(release, inspected.get("revision"))
        try:
            incumbent = self.git.review_workspace(test_source, "evaluator-" + release_id[:16])
            path = self.git.review_workspace(candidate["revision"], "canary-" + release_id[:16])
        except Exception as exc:
            if owned is None:
                raise
            failure = self.artifacts.put(canonical({"stage": "review_workspace",
                                                    "error_type": type(exc).__name__}), "canary-failure")
            return {"verdict": "retry", "reason_code": RETRY_WORKSPACE, "evidence": failure["ref"],
                    "checks": {}, "receipt": receipt}
        receipt["workspaces"] = {"incumbent": {"path": str(incumbent), "revision": test_source},
                                 "candidate": {"path": str(path), "revision": candidate["revision"]}}
        if test_source != candidate["base"]:
            receipt["workspaces"]["incumbent"]["base"] = candidate["base"]
        # Fresh candidate venv; test definitions are taken from the incumbent commit.
        install = self._check([uv_command(), "sync", "--frozen"], path, expected_revision=candidate["revision"])
        if not install["passed"]:
            return self._stop(release, {}, install, receipt)
        python = Path(path) / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        # The services context is entered exactly once (review, PR #57: a second __enter__ re-created
        # the compose directory and left the first stack running). Entry failure is its own receipt;
        # once entered, the stack is always exited, whether the body returns or raises.
        require(bool(self.verification_root), "A verification root is required")
        root = Path(self.verification_root)
        stack = ExitStack()
        try:
            services = (self.verification_services(root, self.artifacts) if owned is None
                        else self.verification_services(root, self.artifacts, project=owned["project"]))
            endpoints = stack.enter_context(services)
        except Exception as exc:
            # INV-CHECK-001: a runner that cannot isolate stops; nothing downstream is a pass.
            failure = self.artifacts.put(canonical({"stage": "verification_isolation", "error": type(exc).__name__ + ": " + str(exc)[:500]}),
                                         "canary-failure")
            return self._stop(release, {}, {"passed": False, "evidence": failure["ref"],
                                            "outcome": "observation_error",
                                            "reason": "verification isolation unavailable"},
                              receipt, RETRY_ISOLATION)
        receipt["project"] = getattr(services, "project", receipt["project"])
        with stack:
            test_env = self.verification_environment(endpoints)
            incumbent_env = {**test_env, "PYTHONPATH": str(Path(incumbent) / "tests")}
            tests = self._check([str(python), "-m", "pytest", str(Path(incumbent) / "tests"),
                "-c", str(Path(incumbent) / "pyproject.toml"), "--import-mode=importlib", "-q"], path, env=incumbent_env,
                expected_revision=candidate["revision"])
            if not tests["passed"]:
                return self._stop(release, {"tests": tests}, tests, receipt)
            candidate_tests = self._check([str(python), "-m", "pytest", "-q"], path, env=test_env,
                                          expected_revision=candidate["revision"])
            if not candidate_tests["passed"]:
                return self._stop(release, {"tests": candidate_tests}, candidate_tests, receipt)
            tests = {"passed": True, "evidence": self.artifacts.put(
                canonical({"incumbent": tests, "candidate": candidate_tests}), "test-suites:" + release_id)["ref"]}
        image = "zeus:candidate-" + candidate["revision"][:16]
        build = self._check(["docker", "build", "-t", image, path], cwd=path, timeout=600, expected_revision=candidate["revision"])
        if not build["passed"]:
            return self._stop(release, {"tests": tests}, build, receipt)
        inspected_image = self.runner(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=30)
        require(inspected_image.returncode == 0, "Candidate image missing")
        # U-2: the id is this attempt's own inspection right after its own build; a later re-tag of
        # the same tag cannot change what is recorded.
        receipt["image"] = {"tag": image, "id": inspected_image.stdout.strip()}
        image = inspected_image.stdout.strip()
        start = self._check(["docker", "run", "--rm", *_labels(owned, ROLE_START), "--memory", "512m",
                             "--cpus", "1", "--entrypoint", "codex", image, "--version"])
        if not start["passed"]:
            return self._stop(release, {"tests": tests, "cli_start": start}, start, receipt)
        task = (self.file_canary(image) if owned is None
                else self.file_canary(image, name=owned["containers"][ROLE_CANARY],
                                      labels=owned["labels"][ROLE_CANARY]))
        checks = {"tests": tests, "cli_start": start, "cli_file_task": task}
        if not task["passed"]:
            return self._stop(release, checks, task, receipt)
        return {"verdict": "checked", "passed": True, "image": image, "checks": checks, "receipt": receipt}

    @staticmethod
    def _require_controller_code(release) -> None:
        """INV-RELEASE-ENVIRONMENT-REVERIFY-001: the recorded controller code, or nothing runs.

        A release without `environment_reverification` is unchanged. One that carries it is evaluated
        only when this process's own code revision is known and equals `controller_revision`.
        """
        if "environment_reverification" not in release:
            return
        record = release["environment_reverification"]
        expected = record.get("controller_revision") if isinstance(record, dict) else None
        if not (type(expected) is str and re.fullmatch(r"[0-9a-f]{40}", expected)):
            raise EvaluatorCodeMismatch("Evaluator code mismatch: no valid controller_revision recorded")
        running = controller_code_revision()
        if running is None:
            raise EvaluatorCodeMismatch("Evaluator code mismatch: running controller revision unknown")
        if running != expected:
            raise EvaluatorCodeMismatch("Evaluator code mismatch: running " + running + " != recorded " + expected)

    def _test_source(self, release, candidate_revision: str | None) -> str:
        """The one commit whose incumbent tests evaluate this release (legacy and owned paths).

        INV-RELEASE-EVALUATOR-MIGRATION-001: an ordinary release runs the tests of candidate.base,
        exactly as before. Otherwise the release must carry the evaluator migration naming that
        revision, and the pin is RE-DERIVED from git here - tree, tests-only paths, patch - never
        trusted from the record; any disagreement is the named refusal `evaluator_pin_mismatch`.
        """
        candidate = release["candidate"]
        source = release["policy"].get("revision", candidate["base"])
        if source == candidate["base"]:
            return source
        pin = release.get("evaluator_migration")

        def check(condition, reason):
            if not condition:
                raise EvaluatorPinMismatch("Evaluator pin mismatch: " + reason)

        check(isinstance(pin, dict) and pin.get("evaluator_revision") == source
              and pin.get("base") == candidate["base"], "no evaluator migration names the test source")
        check(source not in {candidate["revision"], candidate_revision}, "evaluator is the candidate")
        resolved = resolve_evaluator_pin(self.git, source, candidate["base"])
        check(resolved["evaluator_revision"] == source, "evaluator revision")
        # E is a direct child of the base: its one commit is the whole reviewed correction.
        check(resolved["parent"] == resolved["base"], "evaluator parent")
        check(resolved["evaluator_tree"] == pin["evaluator_tree"], "evaluator tree")
        files = resolved["paths"]
        check(bool(files) and files == pin["paths"] and all(f.startswith("tests/") for f in files),
              "evaluator paths")
        check(resolved["patch_sha256"] == pin["patch_sha256"], "evaluator patch")
        return source

    def _run(self, release_id: str) -> dict:
        with self.service.store.transaction() as tx:
            release = tx.get("releases", release_id)
            active = tx.get("deployment", "active")
            image_record = tx.get("images", release_id)
        require(release is not None, "Release not found")
        if release["status"] == "active":
            require(active and active["release_id"] == release_id, "Release is not the active deployment")
            return {"status": "active", "already_applied": True, "pointer": active}
        if release["status"] == "verified":
            require(image_record is not None, "Verified image receipt missing")
            return self._promote(release, active, image_record["image"])
        require(release["status"] == "reviewed", "Release not reviewed")
        candidate = release["candidate"]
        with self.service.store.transaction() as tx:
            self.ticket_binding(tx, candidate)
        current_main = self.git._git("rev-parse", "HEAD")
        if current_main != candidate["base"]:
            request = self.request_rebase(candidate["task_id"], current_main)
            return {"status": "rebasing", "task_id": request["message_id"]}
        # The legacy recorder over the one evaluator: random names, and it alone writes here.
        evaluation = self._evaluate(release, None)
        checks = evaluation["checks"]
        if evaluation["verdict"] == "retry":
            return {"status": "retry", "reason": "verification observation unavailable",
                    "evidence": evaluation["evidence"], "checks": checks}
        if not evaluation["passed"]:
            verified = self.releases.verify(release_id, candidate["revision"], release["policy_hash"], checks)
            return {"status": verified["status"], "checks": checks}
        image = evaluation["image"]
        with self.service.store.transaction() as tx:
            tx.put("images", release_id, {"id": release_id, "image": image, "revision": candidate["revision"]})
        if candidate.get("hook_id"):
            hook_checks = self.hooks(self.service, self.git, self.artifacts).canary(candidate["hook_id"])
            checks.update({"hook_" + name: check for name, check in hook_checks.items()})
            hook = self.service.get_hook(candidate["hook_id"])
            self.service.record_canary(hook["id"], candidate["revision"], digest(hook["spec"]),
                                       {**{name: check["passed"] for name, check in hook_checks.items()},
                                        "cli_start": checks["cli_file_task"]["passed"]})
        verified = self.releases.verify(release_id, candidate["revision"], release["policy_hash"], checks)
        if verified["status"] != "verified":
            return {"status": verified["status"], "checks": checks}
        return self._promote(verified, active, image)

    def _promote(self, release, active, image):
        release_id, candidate, checks = release["id"], release["candidate"], release["checks"]
        self.fence()
        if candidate.get("repository") is not None:
            require(candidate["repository"] == self.git.target_identity(),
                    "Candidate target repository changed since review")
        with self.service.store.transaction() as tx:
            self.ticket_binding(tx, candidate)
            intent = tx.get("promotion_intents", release_id)
        current_main = self.git._git("rev-parse", "HEAD")
        if not intent and current_main != candidate["base"]:
            request = self.request_rebase(
                candidate["task_id"], current_main)
            return {"status": "rebasing", "task_id": request["message_id"]}
        if intent:
            require(intent["status"] != "abandoned", "Promotion abandoned")
            require(intent["candidate_hash"] == digest(candidate) and intent["image"] == image
                    and intent["remote"] == self.git.remote,
                    "Promotion intent identity changed")
        else:
            intent = {"id": release_id, "candidate_hash": digest(candidate), "image": image,
                      "candidate": candidate, "expected_active": (active or {}).get("release_id"),
                      "status": "prepared", "remote": self.git.remote, "at": utcnow(self.clock)}
            with self.service.store.transaction() as tx:
                self.ticket_binding(tx, candidate)
                require(tx.get("promotion_intents", release_id) is None, "Concurrent promotion intent")
                require((tx.get("deployment", "active") or {}).get("release_id") == intent["expected_active"],
                        "Active deployment changed")
                tx.put("promotion_intents", release_id, intent)
        with self.service.store.transaction() as tx:
            require((tx.get("deployment", "active") or {}).get("release_id") == intent["expected_active"],
                    "Active deployment changed")
        # INV-RECOVERY-001: an interrupted external operation needs positive evidence.
        # A local journal cannot prove an unrecorded GitHub merge or implement remote CAS.
        merged = intent.get("merge")
        if intent["remote"] and intent.get("external_started") and not merged:
            return {"status": "blocked_remote", "reason": "Remote side effect needs independent reconciliation"}
        if merged:
            expected_head = merged.get("merged_revision", candidate["revision"])
        else:
            expected_head = candidate["revision"] if not intent["remote"] else None
        if current_main == expected_head:
            require(not self.git._git("status", "--porcelain"), "Main worktree is dirty")
            require(self.git._git("rev-parse", "HEAD^{tree}") == candidate["tree"], "Recovered merge tree mismatch")
            merged = merged or {"merged": True, "revision": candidate["revision"], "transport": "local",
                                "recovered": True}
        elif current_main != candidate["base"] or merged:
            return {"status": "blocked", "reason": "Git position differs from durable promotion intent"}
        else:
            if intent["remote"]:
                self.fence()
                intent["external_started"] = True
                with self.service.store.transaction() as tx:
                    tx.put("promotion_intents", release_id, intent)
                self.git.publish(candidate, "Harness improvement " + candidate["revision"][:12],
                    "Implements a reviewed harness improvement.\n\n"
                    "Independent reviews and incumbent-policy checks:\n"
                    + canonical({"reviews": release["reviews"], "checks": checks}))
            if not self.auto_merge:
                return {"status": "verified", "image": image, "checks": checks}
            self.fence()
            with self.service.store.transaction() as tx:
                self.ticket_binding(tx, candidate)
            merged = self.git.merge(candidate)
            self.fence()
            intent.update(status="merged", merge=merged)
            with self.service.store.transaction() as tx:
                tx.put("promotion_intents", release_id, intent)
        self.fence()
        if not self.auto_merge:
            return {"status": "verified", "image": image, "checks": checks}
        with self.service.store.transaction() as tx:
            pointer = self.releases.promote(release_id, intent["expected_active"], transaction=tx)
            if candidate.get("hook_id"):
                self.service.activate(candidate["hook_id"], transaction=tx)
            tx.put("promotion_intents", release_id, {**intent, "status": "completed", "merge": merged})
        return {"status": "active", "pointer": pointer, "image": image, "merge": merged}

    def abandon(self, release_id, reason):
        """Cancel only a provably unmerged, inactive promotion; never guess remote recovery."""
        require(isinstance(reason, str) and reason.strip(), "Abandon reason required")
        with self.service.store.transaction() as tx:
            intent = tx.get("promotion_intents", release_id)
            require(intent and intent["status"] == "prepared", "No prepared promotion to abandon")
            lock = tx.get("deployment_locks", "controller") or {}
            require(not lock.get("lease_until") or datetime.fromisoformat(lock["lease_until"])
                    <= datetime.now(timezone.utc), "Release controller still running")
            require(not intent.get("external_started") and not intent.get("merge"),
                    "External merge uncertain; independently reconcile GitHub before recovery")
            require(not self.git.is_ancestor(intent["candidate"]["revision"], "HEAD"),
                    "Candidate already in main; resume release recovery instead of abandoning")
            release = tx.get("releases", release_id)
            require(release is not None, "Release not found")
            # This operation changes only ledger state; it never mutates the Git worktree.
            tx.put("promotion_intents", release_id, {**intent, "status": "abandoned", "reason": reason})
            self.releases.cancel(release_id, reason, transaction=tx)
            self.release_queue.cancel(release_id, reason, transaction=tx)
            return {"status": "abandoned", "release_id": release_id}

    def file_canary(self, image: str, name: str | None = None, labels=()) -> dict:
        """INV-RELEASE-FILE-CANARY-001: the codex file task, its ownership handoff and exact postcondition.

        The same owned container, name, labels, auth mount and codex argv as before; only the
        entrypoint is `/bin/sh` running the fixed handoff wrapper. The host then reads both files
        exactly (no stdout fallback), stores a sanitized receipt before the directory is removed and
        records the removal truthfully. `passed` = the command passed AND the postcondition is `ok`.
        """
        require(self.auth.is_file(), "Codex runtime authentication missing")
        script = canary_handoff_script(*_controller_ids())
        directory = tempfile.mkdtemp(prefix="harness-container-canary-")
        # An owned attempt passes its exact name and labels; the legacy runner keeps its random name.
        name = name or "harness-canary-" + os.urandom(6).hex()
        try:
            root = Path(directory)
            token = "HARNESS_CANARY_" + os.urandom(8).hex()
            (root / "input.txt").write_text(token, encoding="utf-8")
            schema = {"type": "object", "additionalProperties": False,
                      "properties": {"value": {"type": "string"}}, "required": ["value"]}
            (root / "schema.json").write_text(canonical(schema), encoding="utf-8")
            command = ["docker", "run", "--rm", "--name", name,
                       *[part for label in labels for part in ("--label", label)],
                       "--memory", "768m", "--cpus", "1",
                       "--mount", f"type=bind,source={root},target=/canary",
                       "--mount", f"type=bind,source={self.auth},target=/root/.codex/auth.json,readonly",
                       "--entrypoint", "/bin/sh", image, "-c", script, "sh",
                       "exec", "--ephemeral", "--skip-git-repo-check",
                       "--sandbox", "danger-full-access", "-c", 'approval_policy="never"',
                       "--output-schema", "/canary/schema.json", "--output-last-message", "/canary/result.json",
                       "-C", "/canary", "Read input.txt and write its exact contents to output.txt. "
                       "Return the input contents in value. Do not use network."]
            try:
                check = self._check(command, timeout=180)
                postcondition = canary_postcondition(root, token)
                try:
                    ref = self.artifacts.put(canonical({"command_ref": check.get("evidence"),
                                                        "command_passed": bool(check["passed"]),
                                                        **postcondition}), "canary-postcondition")["ref"]
                except Exception as exc:
                    # No durable receipt: never a pass, and not a verdict about the candidate either.
                    result = {**check, "passed": False, "outcome": "observation_error", "postcondition": None,
                              "postcondition_reason": "postcondition_artifact_unavailable:" + type(exc).__name__}
                else:
                    result = {**check, "passed": bool(check["passed"]) and postcondition["reason"] == "ok",
                              "postcondition": ref, "postcondition_reason": postcondition["reason"]}
            finally:
                # Docker client timeout alone does not terminate the daemon-owned container.
                self.runner(["docker", "rm", "-f", name], timeout=30)
        finally:
            # Recorded, never raised over the verdict, and never able to turn a failure into a pass.
            cleanup = _remove_canary_directory(directory)
        return {**result, "cleanup": cleanup}

    def _probe_status(self, active, check, component):
        # INV-RECOVERY-001: missing observations cannot certify a bad deployment.
        key = active["release_id"] + ":" + component
        unknown = check.get("outcome") == "observation_error"
        with self.service.store.transaction() as tx:
            previous = tx.get("health_probes", key) or {}
            failures = (0 if check["passed"] else previous.get("failures", 0)
                        if unknown else previous.get("failures", 0) + 1)
            tx.put("health_probes", key, {"id": key, "failures": failures, "at": utcnow(self.clock),
                                         "check": check})
        if check["passed"]:
            return None
        result = {"status": "unknown" if unknown else "unhealthy", "checked_at": utcnow(self.clock),
                  "component": component, "failures": failures, "check": check}
        if not unknown and failures >= POLICY.health_failure_threshold and active.get("previous"):
            previous = self.releases.rollback(active["release_id"], "Repeated CLI health check failure")
            result.update(status="rolled_back", active=previous)
        return result

    def monitor(self) -> dict:
        with self.service.store.transaction() as tx:
            active = tx.get("deployment", "active")
            image = tx.get("images", active["release_id"]) if active else None
        if not image:
            return {"status": "unknown" if active else "no_deployment", "checked_at": utcnow(self.clock)}
        check = self._check(["docker", "run", "--rm", "--memory", "512m", "--entrypoint", "codex",
                             image["image"], "--version"], timeout=45)
        if result := self._probe_status(active, check, "image"):
            return result
        try:
            running = self.runner(["docker", "compose", "ps", "--format", "json"],
                                  cwd=str(self.git.repository), timeout=30, env=self.compose_environment())
            if running.returncode:
                return {"status": "unknown", "checked_at": utcnow(self.clock), "reason": "container listing unavailable"}
            rows = [json.loads(line) for line in running.stdout.splitlines() if line.startswith("{")]
            actual = self.runner(["docker", "image", "inspect", image["image"], "--format", "{{.Id}}"], timeout=20)
            if actual.returncode or not actual.stdout.strip():
                return {"status": "unknown", "checked_at": utcnow(self.clock), "reason": "expected image unavailable"}
            drift = []
            for container in rows:
                if container.get("Service") not in {"conductor", "research-lead", "improvement-lead",
                        "implementation-worker", "github-worker", "geeknews-worker"}:
                    continue
                inspection = self.runner(["docker", "inspect", container["ID"], "--format", "{{.Image}}"], timeout=20)
                if inspection.returncode or not inspection.stdout.strip():
                    return {"status": "unknown", "checked_at": utcnow(self.clock), "reason": "container inspection unavailable"}
                if inspection.stdout.strip() != actual.stdout.strip():
                    drift.append({"service": container["Service"], "expected": actual.stdout.strip(),
                                  "observed": inspection.stdout.strip()})
                    continue
                check = self._check(["docker", "exec", container["ID"], "codex", "--version"], timeout=30)
                if result := self._probe_status(active, check, container["Service"]):
                    return result
            # Idle agents intentionally exit. Absence alone is not image drift.
            return {"status": "degraded" if drift else "healthy", "checked_at": utcnow(self.clock),
                    "check": check, "image_drift": drift}
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
            return {"status": "unknown", "checked_at": utcnow(self.clock), "reason": "container observation unavailable"}

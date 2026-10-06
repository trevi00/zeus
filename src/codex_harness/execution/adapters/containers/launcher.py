"""The four role-container profiles as executor transports: Claude (claude-impl-rw, claude-role-ro) and Codex
(codex-role-ro, codex-impl-rw), each in one owned, verified container, attached over stdio.

Layer: adapters
Context: execution
Owns: `IsolatedClaudeRuntime` (the writable worker: staging, import; the read-only role: the review checkout
    bound read-only), `IsolatedCodexRuntime` (the App Server inside its container with a per-run
    CODEX_HOME credential copy, settled after a confirmed stop), `AttachedAppServer` (the unchanged
    JSON-RPC client over `docker start --attach --interactive`), `parse_line` (the Claude entry's tagged
    protocol lines), `IsolatedWorker` (what composition hands the executor), `ContainerHost` and
    `CredentialBoundary` (the injected host facilities and credential boundary)
Does not own: the argv and control rules (execution.domain.container_spec), docker calls
    (owned_container), the run record and ownership rule (cleanup_ledger), staging and hand-off, the
    credential store and output scrubber (credentials: injected through `CredentialBoundary` and the
    broker), process creation (host_os: injected through `ContainerHost`), the worker-profile documents
    (context: injected), the verifier inspectors (evidence, S8)
Entry points: IsolatedClaudeRuntime, IsolatedCodexRuntime, AttachedAppServer, IsolatedWorker, ContainerHost,
    CredentialBoundary, parse_line
Contracts: INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001, INV-WORKER-SESSION-001, INV-PROJECT-EVIDENCE-001

Moved from SOURCE M7 `adapters/isolated_worker` (IsolatedClaudeRuntime, parse_line, IsolatedWorker) and
`adapters/role_containers` (AttachedAppServer, IsolatedCodexRuntime), characterized first by the
`containers.profiles` golden (the exact docker argv, client environment names and record lifecycle of
each profile up to its before-start refusal). The behaviour is M7's; what M7 reached through module
globals is injected: docker/git/attached-client processes (`ContainerHost`: the host_os chokepoint), the
worker-profile adapter (context), and the credential scrubber/refusal type (`CredentialBoundary`:
credentials). RESEARCH-S3 D6/G7: cancellation is the one bounded stop of `hold`; an unconfirmed stop keeps
the credential copy unsettled for the next admission's reconcile (RC2-F3 5).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from codex_harness.credentials.domain.codex_credential import (
    CODEX_CLI_SHA256,
    CODEX_CLI_VERSION,
    CODEX_CONFIG,
    CODEX_CONFIG_SHA256,
    CODEX_EXECUTABLE,
    CODEX_HOME,
)
from codex_harness.execution.adapters.containers.cleanup_ledger import (
    advance,
    cleanup_debt,
    hold,
    new_record,
    retire,
    unresolved_runs,
)
from codex_harness.execution.adapters.containers.handoff import discard_tree, materialize_handoff
from codex_harness.execution.adapters.containers.owned_container import (
    OwnedContainer,
    docker_environment,
    host_user,
    isolated_review_context,
    preflight,
)
from codex_harness.execution.adapters.containers.staging import (
    apply_import,
    init_standalone_git,
    plan_import,
    scan_tree,
    stage_source,
)
from codex_harness.execution.adapters.providers.codex_app_server import AppServer
from codex_harness.execution.adapters.providers.native_hooks import HOOK_MOUNT, bound_state, verify_bound
from codex_harness.execution.domain.container_spec import (
    CODEX_IMPL_RW,
    CODEX_ROLE_RO,
    DELIVERY_PROTOCOL,
    ENTRY_MODULE,
    EVIDENCE,
    IMAGE,
    MODE,
    PROTOCOLS,
    READ_ONLY_PROTOCOL,
    RESULT,
    TOKEN_NAME,
    TRUSTED_PYTHON,
    WORKSPACE,
    codex_environment,
    container_args,
    read_only_mounts,
    request_protocol,
    summary,
    worker_environment,
)
from codex_harness.execution.domain.worker_sessions import (
    EXPORT_DIRECTORY,
    MODE_FRESH,
    MODE_RESUME,
    RESTORE_DIRECTORY,
)
from codex_harness.kernel.errors import ContractError, IsolationError, require
from codex_harness.kernel.ids import canonical, digest
from codex_harness.kernel.policy import POLICY


@dataclass(frozen=True)
class ContainerHost:
    """The host facilities a role-container transport uses, injected by composition: `runner` runs one
    bounded docker client call (host_os ProcessRunner), `processes` runs host git (host_os
    ChildProcesses), `trees` spawns the owned attached client (`spawn(argv, **kwargs)` -> a tree with
    `process`, `terminate(reason)` and `close()`), `worker_profiles` reads the worker profile
    (`load_profile`, `profile_digest`, `hook_receipts`; None when no profile is configured)."""

    runner: Any
    processes: Any
    trees: Any
    worker_profiles: Any = None


@dataclass(frozen=True)
class CredentialBoundary:
    """The credentials context's output boundary as the Codex transport uses it: `scrubber(issued, path)`
    builds the run's scrubber; `OutputUnsanitizable` is its refusal type (never swallowed here)."""

    scrubber: Any
    OutputUnsanitizable: type


def _scrub(value, secret: str | None):
    if not secret:
        return value
    text = json.dumps(value, ensure_ascii=False)
    return json.loads(text.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "<redacted>")) if secret in text or \
        json.dumps(secret, ensure_ascii=False)[1:-1] in text else value



class IsolatedClaudeRuntime:
    """The executor's transport contract (context manager, `run`, `enters_on_open`) over an owned
    container. It parses no provider stream: events and the result are the inner runtime's."""

    enters_on_open = False
    observer = None  # S10 F2: the executor's process observer, set by `IsolatedWorker.runtime`; None emits nothing

    def __init__(self, config: dict, root, *, model: str, runtime: dict | None = None,
                 max_budget_usd: float | None = None, settings_document: dict | None = None,
                 docker: str = "docker", environment: dict | None = None, watch: tuple = (),
                 project_delivery: dict | None = None, profile: str = "claude-impl-rw", handoff: dict | None = None,
                 host: ContainerHost):
        require(isinstance(config, dict) and config.get("mode") == MODE and IMAGE.fullmatch(str(config.get("image"))),
                "Isolated runtime requires a validated isolation configuration")
        # INV-ROLE-CONTAINER-001: the Claude profiles this runtime composes. The existing writable
        # worker keeps its exact shape; the read-only role binds the review checkout read-only with only
        # its own result directory writable. Anything else refuses before a container exists.
        require(profile in ("claude-impl-rw", "claude-role-ro"), "Unsupported Claude container profile: " + str(profile))
        require(project_delivery is None or profile == "claude-impl-rw", "A read-only role carries no project delivery")
        self.role_profile, self.handoff = profile, handoff
        require(type(model) is str and bool(model.strip()), "Claude requires an explicit model name")
        self.config, self.root, self.docker, self.host = config, Path(root), docker, host
        self.watch = tuple(Path(other) for other in watch)  # sibling record roots: the verifier's replays
        self.model, self.max_budget_usd, self.settings_document = model.strip(), max_budget_usd, settings_document
        # Host paths never cross: the image's own interpreter, executable and evidence root apply.
        self.runtime = {key: value for key, value in dict(runtime or {}).items()
                        if key not in ("profile_interpreter", "profile_evidence_root")}
        self.environment_source = environment
        # INV-PROJECT-EVIDENCE-001 version 2: the host-resolved checklist for THIS candidate, stated in
        # container paths. It is host output, never model output, and it must name this exact image.
        if project_delivery is not None:
            require(isinstance(project_delivery, dict)
                    and (project_delivery.get("execution") or {}).get("image") == config["image"]
                    and project_delivery.get("workspace") == WORKSPACE,
                    "A container project delivery must name this image and the mounted workspace")
        self.project_delivery = project_delivery
        self.profile = self.host.worker_profiles.load_profile(self.runtime["worker_profile"]) if self.runtime.get("worker_profile") is not None else None
        self.container, self.tree, self.record, self.record_path = None, None, None, None
        self.used = False

    def __enter__(self):
        self.preflight = preflight(self.config, self.docker, self.environment_source, runner=self.host.runner)
        return self

    def __exit__(self, *_):
        if self.tree is not None:
            self.tree.terminate("context_exit")
            self.tree.close()
            self.tree = None

    def _advance(self, state: str, **detail) -> None:
        advance(self.record, state, **detail)

    def _end_client(self) -> dict:
        if self.tree is None:
            return {"confirmed": True}
        ended = self.tree.terminate("container_stopped")
        self.tree.close()
        self.tree = None
        return ended

    def run(self, prompt: str, cwd: str, schema: dict, timeout: int = 240, *, on_event=None, on_tick=None,
            read_only: bool = False, model: str | None = None, on_enter=None, cancel=None,
            session_id: str | None = None, task_session: dict | None = None) -> dict:
        require(type(timeout) in (int, float) and 0 < timeout < float("inf"), "Execution timeout must be finite and positive")
        require(type(prompt) is str and bool(prompt), "Claude execution requires a prompt")
        # The profile was chosen from the routing result before this transport existed; a turn of the
        # other shape refuses here, before anything is created (no writable review, no read-only worker).
        require(read_only is (self.role_profile == "claude-role-ro"),
                "The isolated worker is not assigned reviews" if read_only else
                "A read-only Claude role container runs only read-only turns")
        require(not read_only or task_session is None, "A review never opens or resumes a worker session")
        require(not self.used, "This transport object already ran; every attempt builds its own")
        require(model is None or model == self.model, "The requested model differs from the configured Claude model")
        if task_session is not None:
            # INV-WORKER-SESSION-001: an explicit binding only; checked before anything is created.
            require(isinstance(task_session, dict) and task_session.get("mode") in (MODE_FRESH, MODE_RESUME)
                    and task_session.get("session_id") == session_id and session_id is not None,
                    "Task session must name its mode and this run's exact session id")
            require(task_session["mode"] == MODE_FRESH or callable(task_session.get("stage")),
                    "A resumed task session needs the owner's verified archive stage")
        self.used = True
        workspace = str(Path(cwd).resolve())
        pending = [row for root in (self.root, *self.watch) for row in unresolved_runs(root, workspace)]
        if pending:
            # Visible and refused: no duplicate container, no implicit restart, no model retry.
            raise IsolationError("isolation_unresolved_run", json.dumps(pending, sort_keys=True))
        session_id = session_id or str(uuid4())
        run_id = uuid4().hex
        run_directory = self.root / run_id
        staging, evidence = run_directory / "workspace", run_directory / "evidence"
        evidence.mkdir(parents=True)
        self.record_path = run_directory / "run.json"
        self.container = OwnedContainer(self.config, self.docker, run_id, "worker", runner=self.host.runner)
        self.record = new_record(run_directory, role="worker", workspace=workspace, config=self.config,
                                 container=self.container, session_id=session_id, staging=str(staging),
                                 evidence=str(evidence))
        source_environment = os.environ if self.environment_source is None else self.environment_source
        secret = source_environment.get(TOKEN_NAME)
        try:
            revision = self.host.processes.run(["git", "-C", workspace, "rev-parse", "HEAD"], capture_output=True,
                                               text=True, timeout=60)
            if revision.returncode != 0:
                raise IsolationError("source_revision_unavailable")
            dirty = self.host.processes.run(["git", "-C", workspace, "status", "--porcelain"], capture_output=True,
                                            text=True, timeout=120)
            if dirty.returncode != 0 or dirty.stdout.strip():
                raise IsolationError("source_candidate_dirty")
            if read_only:
                return self._run_read_only(request_fields={"prompt": prompt, "schema": schema, "timeout": timeout,
                                                           "session_id": session_id},
                                           workspace=workspace, run_directory=run_directory, evidence=evidence,
                                           revision=revision.stdout.strip(), secret=secret, on_event=on_event,
                                           on_tick=on_tick, on_enter=on_enter, cancel=cancel)
            # The caller's existing per-call heartbeat covers preparation too: an execution whose
            # lease ended, was superseded or was cancelled while its source was being staged stops
            # here, before the container exists. The refusal is the caller's own and travels
            # unchanged; only the retained record notes where it happened.
            cancelled = []
            def prepared_tick():
                try:
                    on_tick()
                except BaseException:
                    cancelled.append("preparation")
                    raise
            try:
                source = stage_source(workspace, revision.stdout.strip(), staging, processes=self.host.processes,
                                      on_progress=None if on_tick is None else prepared_tick)
            except BaseException:
                if cancelled:
                    # Proven never to have created a container: a refusal that never ran, with its
                    # owned preparation record retained for the operator.
                    try:
                        self._advance("refused", reason="preparation_cancelled")
                    except IsolationError:
                        pass   # unwritable record: it stays unresolved, and the caller's own
                        # refusal still reaches the caller instead of being replaced here
                raise
            git_report = init_standalone_git(staging, processes=self.host.processes)
            session_request = None
            if task_session is not None:
                # The verified archive is staged into THIS run's own evidence mount before the container
                # exists; the entry re-verifies it against the manifest named here. No other task's home
                # or directory is ever mounted.
                manifest = None
                if task_session["mode"] == MODE_RESUME:
                    try:
                        manifest = task_session["stage"](evidence / RESTORE_DIRECTORY)
                    except (ContractError, OSError) as exc:
                        raise IsolationError("task_session_stage_failed",
                                             getattr(exc, "reason", type(exc).__name__)) from exc
                session_request = {"mode": task_session["mode"], "session_id": session_id, "manifest": manifest,
                                   "restore": EVIDENCE + "/" + RESTORE_DIRECTORY if manifest is not None else None,
                                   "export": EVIDENCE + "/" + EXPORT_DIRECTORY}
            self._advance("prepared", source={key: source[key] for key in ("revision", "files", "bytes", "manifest_sha256")},
                          **({} if session_request is None else
                             {"task_session": {"mode": session_request["mode"], "session_id": session_id}}))
            entry = [TRUSTED_PYTHON, "-I", "-m", ENTRY_MODULE]
            environment = worker_environment()
            args = container_args(self.config, name=self.container.name, run_id=run_id, role="worker", network="bridge",
                                  mounts=[(str(staging.resolve()), WORKSPACE), (str(evidence.resolve()), EVIDENCE)],
                                  environment=environment, pass_names=(TOKEN_NAME,), entry=entry, workdir="/",
                                  user=host_user())
            require(secret is None or all(secret not in part for part in args), "A credential value reached an argv")
            try:
                container_id = self.container.create(args, docker_environment(self.environment_source, token=True))
            except IsolationError:
                self._advance("refused", reason="container_create_failed")
                raise
            self.record["container"] = container_id
            try:
                self._advance("created", container=container_id)
                controls = self.container.verify({WORKSPACE, EVIDENCE}, "bridge")
            except IsolationError as exc:
                removal = self.container.remove()  # never started: exact id, not forced
                self._advance("refused" if removal["removed"] else "created", reason=exc.reason_code)
                raise
        except IsolationError:
            if self.record["state"] is None:
                self._advance("refused", reason="before_container")
            raise
        request = {"protocol": request_protocol(self.project_delivery is not None, session_request is not None),
                   "prompt": prompt, "schema": schema, "timeout": timeout, "model": self.model,
                   "session_id": session_id, "runtime": self.runtime, "max_budget_usd": self.max_budget_usd,
                   "settings_document": self.settings_document, "cwd": WORKSPACE, "evidence_root": EVIDENCE}
        if self.project_delivery is not None:
            request["project_delivery"] = self.project_delivery
        if session_request is not None:
            request["task_session"] = session_request
        started = time.monotonic()

        def converse():
            if on_enter is not None:
                on_enter()
            return self._converse(request, timeout, on_event=on_event, on_tick=on_tick, cancel=cancel)
        # External-effect boundary (`start_requested`, written by `hold`): from here on nothing is a
        # refusal that never ran, and the container is stopped however the conversation ends.
        stream, stopped = hold(self.container, self.record, converse, client=self._end_client, detail=lambda value: {
            "stream": {key: value[key] for key in ("reason", "violation", "lines")}}, observer=self.observer)
        if not stopped["confirmed"]:
            raise ContractError("Isolated worker container termination could not be confirmed; the outcome is unknown; "
                                "recovery record " + str(self.record_path))
        inner = stream["result"]
        receipts = (self.host.worker_profiles.hook_receipts(
            evidence / session_id, self.host.worker_profiles.profile_digest(self.profile)) if self.profile is not None else None)
        isolation = {**summary(self.config), "run_id": run_id, "container": {"id": self.container.id, "name": self.container.name,
                                                                           "controls": controls, "stop": stopped},
                     "source": {key: source[key] for key in ("revision", "files", "bytes", "manifest_sha256")},
                     "staging_git": git_report, "preflight": self.preflight, "record": str(self.record_path),
                     "credential": {"name": TOKEN_NAME, "transport": "docker client environment by name; never argv"},
                     "cli_version": ((inner or {}).get("command") or {}).get("cli_version"),
                     "harness": {"profile_digest": self.host.worker_profiles.profile_digest(self.profile) if self.profile is not None else None,
                                 "document_sha256": self.profile.get("document_sha256") if self.profile else None,
                                 "host_observed_hook_receipts": receipts,
                                 "note": "receipts are files the hook wrote into the mounted evidence directory, read "
                                         "by the host after the container stopped; absence is not observed, never assumed"},
                     "stream": {key: stream[key] for key in ("reason", "violation", "lines", "stderr_tail")},
                     "project_evidence": None if self.project_delivery is None else {
                         "protocol": DELIVERY_PROTOCOL, "profile_digest": self.project_delivery.get("profile_digest"),
                         "project_digest": self.project_delivery.get("project_digest"),
                         "execution": dict(self.project_delivery["execution"]),
                         "checks": [entry["check_id"] for entry in self.project_delivery.get("commands", [])],
                         "document_sha256": digest(self.project_delivery["document"]),
                         "note": "host-authored checklist delivered into the container; compliance is decided by "
                                 "the isolated replay, not by this delivery"},
                     "elapsed_seconds": time.monotonic() - started}
        if session_request is not None and inner is not None:
            # The entry's report is a claim; the owner re-verifies every byte from the host path.
            reported = inner.get("task_session") if isinstance(inner.get("task_session"), dict) else {}
            inner = {**inner, "task_session": {
                "mode": session_request["mode"], "session_id": session_id,
                "exported": bool(reported.get("exported")) and reported.get("export") == session_request["export"]
                and reported.get("session_id") == session_id,
                "export": str(evidence / EXPORT_DIRECTORY),
                "reported": {key: reported.get(key) for key in ("exported", "files", "excluded", "transcript_sha256",
                                                                 "manifest_sha256", "error")}}}
        failure = None
        try:
            if inner is None:
                failure = IsolationError("protocol_result_missing", str(stream["violation"] or stream["reason"]))
            else:
                plan = plan_import(source["manifest"], staging)
                self._advance("validated", changes={key: len(plan[key]) for key in ("added", "modified", "deleted")})
                isolation["import"] = apply_import(plan, staging, Path(workspace))
                self._advance("imported")
        except IsolationError as exc:
            failure = exc
        except OSError as exc:
            failure = IsolationError("import_failed", type(exc).__name__)
        isolation["outcome"] = "imported" if failure is None else failure.reason_code
        # The whole redacted inner result is retained beside the record before the container is removed.
        removal = retire(self.container, self.record,
                         _scrub({"isolation": isolation, "inner_failure": (inner or {}).get("failure"),
                                 "inner_terminal": (inner or {}).get("terminal")}, secret), isolation["outcome"],
                         files={"inner_result.json": _scrub(inner, secret)} if inner is not None else None,
                         removed={"staging_retained": failure is not None}, observer=self.observer)
        isolation["cleanup"] = {**removal, "staging_retained": failure is not None or not removal["removed"]}
        if not removal["evidence_written"]:
            raise ContractError("Isolated worker evidence could not be written; the stopped container and staging are "
                                "retained; recovery record " + str(self.record_path))
        if removal["removed"] and failure is None:
            shutil.rmtree(staging, ignore_errors=True)  # this run's own staging; evidence and record stay
        if failure is not None:
            # Entered and not importable: never a success, never a partial import, staging preserved.
            raise ContractError(str(failure) + "; staging preserved; recovery record " + str(self.record_path)) from failure
        return _scrub({**inner, "isolation": isolation}, secret)

    def _run_read_only(self, *, request_fields: dict, workspace: str, run_directory: Path, evidence: Path,
                       revision: str, secret, on_event, on_tick, on_enter, cancel) -> dict:
        """claude-role-ro (INV-ROLE-CONTAINER-001): the clean review checkout bound READ-ONLY at the
        workspace, this run's own result directory as the only writable bind, the immutable evidence
        hand-off (if any) read-only. Nothing is staged or imported; the executor's clean/HEAD checks
        still follow. Ownership, stop, retention and removal are the one shared rule (`hold`/`retire`)."""
        session_id = request_fields["session_id"]
        try:
            handoff = materialize_handoff(self.handoff, run_directory / "handoff")
            self._advance("prepared", source={"revision": revision, "mode": "read_only_checkout"},
                          profile=self.role_profile, handoff=None if handoff is None else handoff["summary"])
            mounts, expected = read_only_mounts(workspace, str(evidence.resolve()), handoff)
            entry = [TRUSTED_PYTHON, "-I", "-m", ENTRY_MODULE]
            environment = worker_environment()
            args = container_args(self.config, name=self.container.name, run_id=self.container.run_id, role="worker",
                                  network="bridge", mounts=mounts, environment=environment, pass_names=(TOKEN_NAME,),
                                  entry=entry, workdir="/", user=host_user())
            require(secret is None or all(secret not in part for part in args), "A credential value reached an argv")
            try:
                container_id = self.container.create(args, docker_environment(self.environment_source, token=True))
            except IsolationError:
                self._advance("refused", reason="container_create_failed")
                raise
            self.record["container"] = container_id
            try:
                self._advance("created", container=container_id)
                controls = self.container.verify(expected, "bridge")
            except IsolationError as exc:
                removal = self.container.remove()
                self._advance("refused" if removal["removed"] else "created", reason=exc.reason_code)
                raise
        except IsolationError:
            if self.record["state"] is None:
                self._advance("refused", reason="before_container")
            raise
        request = {"protocol": READ_ONLY_PROTOCOL, "prompt": request_fields["prompt"], "schema": request_fields["schema"],
                   "timeout": request_fields["timeout"], "model": self.model, "session_id": session_id,
                   "runtime": self.runtime, "max_budget_usd": self.max_budget_usd,
                   "settings_document": self.settings_document, "cwd": WORKSPACE, "evidence_root": EVIDENCE,
                   "read_only": True}
        started = time.monotonic()
        timeout = request_fields["timeout"]

        def converse():
            if on_enter is not None:
                on_enter()
            return self._converse(request, timeout, on_event=on_event, on_tick=on_tick, cancel=cancel)
        stream, stopped = hold(self.container, self.record, converse, client=self._end_client, detail=lambda value: {
            "stream": {key: value[key] for key in ("reason", "violation", "lines")}}, observer=self.observer)
        if not stopped["confirmed"]:
            raise ContractError("Isolated worker container termination could not be confirmed; the outcome is unknown; "
                                "recovery record " + str(self.record_path))
        inner = stream["result"]
        receipts = (self.host.worker_profiles.hook_receipts(
            evidence / session_id, self.host.worker_profiles.profile_digest(self.profile)) if self.profile is not None else None)
        isolation = {**summary(self.config), "profile": self.role_profile, "run_id": self.container.run_id,
                     "container": {"id": self.container.id, "name": self.container.name, "controls": controls,
                                   "stop": stopped},
                     "source": {"revision": revision, "mode": "read_only_checkout"},
                     "handoff": None if handoff is None else handoff["summary"],
                     "preflight": self.preflight, "record": str(self.record_path),
                     "credential": {"name": TOKEN_NAME, "transport": "docker client environment by name; never argv"},
                     "cli_version": ((inner or {}).get("command") or {}).get("cli_version"),
                     "harness": {"profile_digest": self.host.worker_profiles.profile_digest(self.profile) if self.profile is not None else None,
                                 "host_observed_hook_receipts": receipts},
                     "stream": {key: stream[key] for key in ("reason", "violation", "lines", "stderr_tail")},
                     "elapsed_seconds": time.monotonic() - started}
        outcome = "reviewed" if inner is not None else "protocol_result_missing"
        isolation["outcome"] = outcome
        removal = retire(self.container, self.record,
                         _scrub({"isolation": isolation, "inner_failure": (inner or {}).get("failure"),
                                 "inner_terminal": (inner or {}).get("terminal")}, secret), outcome,
                         files={"inner_result.json": _scrub(inner, secret)} if inner is not None else None,
                         observer=self.observer)
        isolation["cleanup"] = removal
        if not removal["evidence_written"]:
            raise ContractError("Isolated worker evidence could not be written; the stopped container is retained; "
                                "recovery record " + str(self.record_path))
        if inner is None:
            # Entered and no result: never a success; the read-only checkout was never writable.
            raise ContractError("isolated worker: protocol_result_missing: " + str(stream["violation"] or stream["reason"])
                                + "; recovery record " + str(self.record_path))
        return _scrub({**inner, "isolation": isolation}, secret)

    def _converse(self, request: dict, timeout, *, on_event, on_tick, cancel) -> dict:
        """Start attached, send one request, forward tagged events; every irregularity is named."""
        limits = self.config["limits"]
        # An event is one inner line (already bounded by the runtime); the result carries no events.
        line_limit = max(4 * POLICY.claude_line_bytes + 65536, 16 * 1024 * 1024)
        self.tree = self.host.trees.spawn([self.docker, "start", "--attach", "--interactive", self.container.id],
                                      env=docker_environment(self.environment_source), stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process = self.tree.process
        self._advance("running", client_pid=process.pid)
        inbox: queue.Queue = queue.Queue(maxsize=POLICY.claude_event_queue)
        tail = [b""]

        def send():
            try:
                process.stdin.write(canonical(request).encode("utf-8") + b"\n")
                process.stdin.close()
            except OSError:
                pass

        def read():
            try:
                while line := process.stdout.readline(line_limit + 1):
                    inbox.put(line)
            except (OSError, ValueError):
                pass
            inbox.put(None)

        def errors():
            try:
                while block := process.stderr.read(4096):
                    tail[0] = (tail[0] + block)[-4096:]
            except (OSError, ValueError):
                pass
        threads = [threading.Thread(target=target, daemon=True) for target in (send, read, errors)]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + float(timeout) + limits["inner_grace_seconds"]
        events, result, reason, violation, lines, dropped = [], None, None, None, 0, 0
        # A lease check or observer that raises here propagates to `hold`, which owns the stop.
        while reason is None:
            if cancel is not None and cancel():
                reason = "cancelled"
                break
            if on_tick is not None:
                on_tick()
            if time.monotonic() >= deadline:
                reason = "deadline"
                break
            try:
                line = inbox.get(timeout=0.25)
            except queue.Empty:
                continue
            if line is None:
                reason = "stream_closed"
                break
            lines += 1
            message = parse_line(line, line_limit)
            if message is None or result is not None:
                violation = "invalid_line" if message is None else "output_after_result"
                reason, result = "protocol_violation", None
                break
            if message["kind"] == "event":
                if len(events) < POLICY.claude_events_retained:
                    events.append(message["event"])
                else:
                    dropped += 1
                if on_event is not None:
                    on_event(message["event"])
            elif message["kind"] == "result":
                result = message["result"]
            elif message["kind"] == "refused":
                violation, reason = "inner_refused:" + str(message.get("error_type")), "inner_refused"
        if result is not None and reason == "stream_closed":
            result = {**result, "events": events}
        else:
            violation = violation or ("truncated_before_result" if reason == "stream_closed" else reason)
            result = None
        return {"result": result, "reason": reason, "violation": violation, "lines": lines, "events_dropped": dropped,
                "stderr_tail": tail[0].decode("utf-8", errors="replace")}



def parse_line(line: bytes, limit: int) -> dict | None:
    """One tagged protocol line, or None for anything else: overlong, unterminated, untagged, mistyped."""
    if len(line) > limit or not line.endswith(b"\n"):
        return None
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(message, dict) or message.get("protocol") not in PROTOCOLS:
        return None
    kind = message.get("kind")
    if kind in ("entered", "refused"):
        return message
    if kind in ("event", "result") and isinstance(message.get(kind), dict):
        return message
    return None



class _TextProcess:
    """The attached docker client's binary pipes, as the text streams the protocol code reads."""

    def __init__(self, process):
        self.raw, self.pid = process, process.pid
        self.stdin = io.TextIOWrapper(process.stdin, encoding="utf-8", write_through=True)
        self.stdout = io.TextIOWrapper(process.stdout, encoding="utf-8", errors="replace")
        self.stderr = io.TextIOWrapper(process.stderr, encoding="utf-8", errors="replace")

    def poll(self):
        return self.raw.poll()


class AttachedAppServer(AppServer):
    """The unchanged JSON-RPC client over the stdio of `docker start --attach --interactive`. The
    container and the client tree are owned by `hold`; this closes only its own input on exit."""

    def __init__(self, process, cwd_target: str):
        super().__init__(executable=CODEX_EXECUTABLE)
        self.attached, self.cwd_target = _TextProcess(process), cwd_target

    def _spawn(self, argv):
        return self.attached

    def thread_cwd(self, cwd) -> str:
        return self.cwd_target

    def __exit__(self, *_):
        try:
            self.attached.stdin.close()
        except (OSError, ValueError):
            pass


class IsolatedCodexRuntime:
    """The executor's transport contract (context manager, `run`, `enters_on_open`) for codex-role-ro
    and codex-impl-rw. The protocol, schema, usage and turn semantics are the App Server client's."""

    enters_on_open = False
    observer = None  # S10 F2: the executor's process observer, set by `IsolatedWorker.codex_runtime`; None emits nothing

    def __init__(self, config: dict, root, *, profile: str, broker, docker: str = "docker",
                 environment: dict | None = None, watch: tuple = (), context_window=None, handoff=None,
                 state_root=None, lock_wait_seconds: float = 60.0, network: str = "bridge", host: ContainerHost,
                 credentials: CredentialBoundary, native_hooks=None):
        require(isinstance(config, dict) and config.get("mode") == MODE and IMAGE.fullmatch(str(config.get("image"))),
                "Isolated runtime requires a validated isolation configuration")
        require(profile in (CODEX_ROLE_RO, CODEX_IMPL_RW), "Unsupported Codex container profile: " + str(profile))
        self.config, self.root, self.role_profile, self.broker, self.docker = config, Path(root), profile, broker, docker
        self.environment_source, self.watch = environment, tuple(Path(other) for other in watch)
        # `network` is the profile's worker network; only a no-provider fixture ever passes "none".
        self.context_window, self.handoff, self.network = context_window, handoff, network
        self.state_root = None if state_root is None else Path(state_root)
        self.lock_wait_seconds = lock_wait_seconds
        self.host, self.credentials = host, credentials
        # S3b (design v2 §5.4): `native_hooks(destination) -> ContainerHookSet | None` builds this run's
        # verified, digest-addressed hook set (execution.adapters.providers.native_hooks); None = no hooks.
        self.native_hooks = native_hooks
        self.container, self.tree, self.record, self.record_path = None, None, None, None
        self.used = False

    def __enter__(self):
        # No Claude token is required or forwarded: a Codex container holds exactly one provider credential.
        self.preflight = preflight(self.config, self.docker, self.environment_source, token=False, runner=self.host.runner)
        return self

    def __exit__(self, *_):
        if self.tree is not None:
            self.tree.terminate("context_exit")
            self.tree.close()
            self.tree = None

    def _advance(self, state: str, **detail) -> None:
        advance(self.record, state, **detail)

    def _end_client(self) -> dict:
        if self.tree is None:
            return {"confirmed": True}
        ended = self.tree.terminate("container_stopped")
        self.tree.close()
        self.tree = None
        return ended

    def _state_directory(self, state_key) -> Path:
        return self.state_root / digest({"state_key": state_key, "profile": self.role_profile})

    def run(self, prompt: str, cwd: str, schema: dict, timeout: int = 240, *, on_event=None, read_only: bool = False,
            on_tick=None, model: str | None = None, on_enter=None, thread_id: str | None = None,
            state_key: str | None = None) -> dict:
        require(type(timeout) in (int, float) and 0 < timeout < float("inf"), "Execution timeout must be finite and positive")
        require(type(prompt) is str and bool(prompt), "Codex execution requires a prompt")
        require(read_only is (self.role_profile == CODEX_ROLE_RO),
                "A codex-role-ro container runs only read-only turns" if not read_only else
                "A codex-impl-rw container is not assigned reviews")
        # Task-scoped CLI state is reused only by the SAME task on the writable profile; a reviewer
        # always starts from a fresh home (D3 v3 item 2).
        require(state_key is None or (not read_only and self.state_root is not None),
                "Retained Codex state belongs to one writable task only")
        require(not self.used, "This transport object already ran; every attempt builds its own")
        self.used = True
        workspace = str(Path(cwd).resolve())
        pending = [row for root in (self.root, *self.watch) for row in unresolved_runs(root, workspace)]
        if pending:
            raise IsolationError("isolation_unresolved_run", json.dumps(pending, sort_keys=True))
        admission = self.broker.admit(wait_seconds=min(self.lock_wait_seconds, float(timeout)), on_tick=on_tick)
        try:
            return self._admitted(admission, prompt, workspace, schema, timeout, on_event=on_event,
                                  read_only=read_only, on_tick=on_tick, model=model, on_enter=on_enter,
                                  thread_id=thread_id, state_key=state_key)
        finally:
            admission.release()

    def _prepare(self, admission, workspace, run_directory, read_only, state_key, on_tick) -> dict:
        # Published before anything is created, so a refusal part-way still discards what exists.
        prepared = self.prepared = {"handoff": None, "source": None, "staging_git": None,
                                    "home": run_directory / "codex-home", "handoff_path": run_directory / "handoff"}
        revision = self.host.processes.run(["git", "-C", workspace, "rev-parse", "HEAD"], capture_output=True,
                                           text=True, timeout=60)
        if revision.returncode != 0:
            raise IsolationError("source_revision_unavailable")
        dirty = self.host.processes.run(["git", "-C", workspace, "status", "--porcelain"], capture_output=True,
                                        text=True, timeout=120)
        if dirty.returncode != 0 or dirty.stdout.strip():
            raise IsolationError("source_candidate_dirty")
        home, config = run_directory / "codex-home", run_directory / "codex-config.toml"
        if read_only:
            result = run_directory / "result"
            result.mkdir()
            prepared.update(source={"revision": revision.stdout.strip(), "mode": "read_only_checkout"}, result=result)
            mounts = [(workspace, WORKSPACE, True), (str(result.resolve()), RESULT)]
            expected = {WORKSPACE: False, RESULT: True}
        else:
            staging, evidence = run_directory / "workspace", run_directory / "evidence"
            evidence.mkdir()
            source = stage_source(workspace, revision.stdout.strip(), staging, processes=self.host.processes,
                                  on_progress=on_tick)
            prepared.update(source=source, staging=staging, evidence=evidence,
                            staging_git=init_standalone_git(staging, processes=self.host.processes))
            mounts = [(str(staging.resolve()), WORKSPACE), (str(evidence.resolve()), EVIDENCE)]
            expected = {WORKSPACE: True, EVIDENCE: True}
        handoff = materialize_handoff(self.handoff, run_directory / "handoff")
        if handoff is not None:
            mounts.append((handoff["source"], handoff["target"], True))
            expected[handoff["target"]] = False
        prepared["handoff"] = handoff
        # S3b: the verified hook scripts, read-only at the fixed container path the commands name.
        hook_set = self.native_hooks(run_directory / "hooks") if self.native_hooks is not None else None
        if hook_set is not None:
            mounts.append((hook_set.source, HOOK_MOUNT, True))
            expected[HOOK_MOUNT] = False
        prepared["hooks"] = hook_set
        home.mkdir(mode=0o700)
        if state_key is not None and self._state_directory(state_key).is_dir():
            shutil.copytree(self._state_directory(state_key), home, symlinks=True, dirs_exist_ok=True)
        config.write_text(CODEX_CONFIG, encoding="utf-8")
        config.chmod(0o444)
        if hashlib.sha256(config.read_bytes()).hexdigest() != CODEX_CONFIG_SHA256:
            raise IsolationError("codex_config_digest_mismatch", "before start")
        prepared["credential"] = admission.issue(self.container.run_id, self.record_path, home)
        mounts += [(str(home.resolve()), CODEX_HOME), (str(config.resolve()), CODEX_HOME + "/config.toml", True)]
        expected.update({CODEX_HOME: True, CODEX_HOME + "/config.toml": False})
        prepared.update(home=home, config=config, mounts=mounts, expected=expected)
        return prepared

    def _admitted(self, admission, prompt, workspace, schema, timeout, *, on_event, read_only, on_tick, model,
                  on_enter, thread_id, state_key) -> dict:
        run_id = uuid4().hex
        run_directory = self.root / run_id
        run_directory.mkdir(parents=True)
        self.record_path = run_directory / "run.json"
        self.container = OwnedContainer(self.config, self.docker, run_id, "codex", runner=self.host.runner)
        self.record = new_record(run_directory, role="codex", workspace=workspace, config=self.config,
                                    container=self.container, profile=self.role_profile)
        self.prepared = None
        try:
            prepared = self._prepare(admission, workspace, run_directory, read_only, state_key, on_tick)
            scrubber = self.credentials.scrubber(admission.data, prepared["home"] / "auth.json")
            self._advance("prepared", profile=self.role_profile, config_sha256=CODEX_CONFIG_SHA256,
                          source={key: prepared["source"][key] for key in ("revision",)},
                          handoff=None if prepared["handoff"] is None else prepared["handoff"]["summary"],
                          credential={"store": "per-run copy issued", "ledger": "issued"})
            hook_set, hook_state = prepared["hooks"], {}
            if hook_set is not None:
                try:
                    hook_state = self._bind_hooks(prepared, workspace, scrubber, admission)
                except BaseException as exc:
                    if self.record["state"] in ("prepared", "hook_discovery_bound"):
                        # No run container was ever created: a refusal that never ran, resolved by name.
                        self._advance("refused", reason="hook_discovery_" + getattr(exc, "reason_code",
                                                                                   type(exc).__name__))
                    raise
            probe = AppServer(executable=CODEX_EXECUTABLE, context_window=self.context_window,
                              hooks=None if hook_set is None else hook_set.configuration)
            probe.hook_state = hook_state
            entry = [CODEX_EXECUTABLE, *probe.server_arguments()]
            args = container_args(self.config, name=self.container.name, run_id=run_id, role="codex",
                                     network=self.network, mounts=prepared["mounts"], environment=codex_environment(),
                                     pass_names=(), entry=entry, workdir=WORKSPACE, user=host_user())
            try:
                container_id = self.container.create(args, docker_environment(self.environment_source))
            except IsolationError:
                self._advance("refused", reason="container_create_failed")
                raise
            self.record["container"] = container_id
            try:
                self._advance("created", container=container_id)
                controls = self.container.verify(prepared["expected"], self.network)
            except IsolationError as exc:
                removal = self.container.remove()
                self._advance("refused" if removal["removed"] else "created", reason=exc.reason_code)
                raise
        except BaseException:
            if self.record["state"] is None:
                try:
                    self._advance("refused", reason="before_container")
                except IsolationError:
                    pass
            self._settle_quietly(admission)
            if admission.entry is None or admission.entry.get("state") != "issued":
                # An unsettled copy (a dependent discovery container not proven gone) stays for reconcile.
                self._discard(self.prepared)
            raise
        started = time.monotonic()
        forwarded = {}

        def forward(event):
            # INV-CODEX-CREDENTIAL-001: nothing leaves this layer before the output boundary saw it.
            clean = forwarded[id(event)] = scrubber.event(event)
            if on_event is not None:
                on_event(clean)

        def converse():
            if on_enter is not None:
                on_enter()
            self.tree = self.host.trees.spawn([self.docker, "start", "--attach", "--interactive", self.container.id],
                                             env=docker_environment(self.environment_source),
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._advance("running", client_pid=self.tree.process.pid)
            server = AttachedAppServer(self.tree.process, WORKSPACE)
            with server:
                replaced = None
                try:
                    if hook_set is not None:
                        # S3b: bound, discovered, trusted and unchanged, or refused (never silently skipped).
                        server.hooks, server.hook_state = hook_set.configuration, hook_state
                        rows = server.request("hooks/list", {"cwds": [WORKSPACE]}, 30)["data"]
                        self._advance("hooks_verified", statuses=verify_bound(rows, hook_set, hook_state),
                                      digests=list(hook_set.digests))
                    value = server.run(prompt, workspace, schema, timeout, thread_id=thread_id, on_event=forward,
                                       read_only=read_only, on_tick=on_tick, model=model)
                except self.credentials.OutputUnsanitizable:
                    raise
                except Exception as exc:
                    replaced = scrubber.failure(exc)
                    if replaced is exc:
                        raise
                if replaced is not None:
                    raise replaced  # outside the handler: the original text is never chained or displayed
                return scrubber.result(value, forwarded)
        try:
            value, stopped = hold(self.container, self.record, converse, client=self._end_client, detail=lambda v: {
                "turn": {"interrupted": v.get("interrupted"), "failure": (v.get("failure") or {}).get("cause")}},
                observer=self.observer)
        except BaseException as exc:
            # However the turn ended, the credential copy is settled only when the stop was confirmed;
            # an unconfirmed stop keeps the copy and its ledger entry for the next admission's reconcile.
            if cleanup_debt(self.record) is None:
                try:
                    self._after_stop(admission, prepared)
                    self._discard(prepared)
                except IsolationError as held:
                    # Quarantined: the marker holds every next admission; the home stays as evidence. An
                    # unreadable per-run credential is that same hold, so the hold is what is reported.
                    if isinstance(exc, self.credentials.OutputUnsanitizable):
                        raise held from exc
            raise
        if not stopped["confirmed"]:
            raise ContractError("Codex role container termination could not be confirmed; the outcome is unknown and "
                                "its credential copy stays unsettled; recovery record " + str(self.record_path))
        try:
            settlement = self._after_stop(admission, prepared)
        except IsolationError as exc:
            # Hold: the store is quarantined; the stopped container is still retired by the one rule,
            # and the per-run home stays as the owner's evidence.
            retire(self.container, self.record, {"credential_hold": exc.reason_code, "detail": str(exc)},
                      "credential_hold", observer=self.observer)
            raise
        isolation = {**summary(self.config), "profile": self.role_profile, "run_id": run_id,
                     "container": {"id": self.container.id, "name": self.container.name, "controls": controls,
                                   "stop": stopped},
                     "source": {key: prepared["source"][key] for key in ("revision", "files", "bytes", "manifest_sha256", "mode")
                                if key in prepared["source"]},
                     "staging_git": prepared["staging_git"], "preflight": self.preflight, "record": str(self.record_path),
                     "handoff": None if prepared["handoff"] is None else prepared["handoff"]["summary"],
                     "credential": {"transport": "per-run CODEX_HOME copy; credential-only write-back under the lock",
                                    "settlement": settlement["state"], "account_sha256": prepared["credential"]["account_sha256"]},
                     "cli": {"pinned_version": CODEX_CLI_VERSION, "pinned_sha256": CODEX_CLI_SHA256,
                             "config_sha256": CODEX_CONFIG_SHA256},
                     "elapsed_seconds": time.monotonic() - started}
        failure = None
        if not read_only:
            try:
                plan = plan_import(prepared["source"]["manifest"], prepared["staging"])
                self._advance("validated", changes={key: len(plan[key]) for key in ("added", "modified", "deleted")})
                isolation["import"] = apply_import(plan, prepared["staging"], Path(workspace))
                self._advance("imported")
            except IsolationError as exc:
                failure = exc
            except OSError as exc:
                failure = IsolationError("import_failed", type(exc).__name__)
        else:
            try:
                isolation["result_files"] = scan_tree(prepared["result"], skip_top_git=False)
            except IsolationError as exc:
                isolation["result_files"] = {"refused": exc.reason_code}
        isolation["outcome"] = ("reviewed" if read_only else "imported") if failure is None else failure.reason_code
        retained = scrubber.scrub({key: value.get(key) for key in ("answer", "thread_id", "usage", "interrupted", "failure",
                                                                   "inspection_blocked", "requested_model")})
        removal = retire(self.container, self.record, scrubber.scrub({"isolation": isolation}), isolation["outcome"],
                            files={"codex_result.json": retained},
                            removed={"staging_retained": failure is not None}, observer=self.observer)
        isolation["cleanup"] = removal
        if not removal["evidence_written"]:
            raise ContractError("Codex role container evidence could not be written; the stopped container is "
                                "retained; recovery record " + str(self.record_path))
        if failure is not None:
            raise ContractError(str(failure) + "; staging preserved; recovery record " + str(self.record_path)) from failure
        if not read_only and removal["removed"]:
            shutil.rmtree(prepared["staging"], ignore_errors=True)
        if state_key is not None:
            target = self._state_directory(state_key)
            discard_tree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(prepared["home"], target, symlinks=True,
                            ignore=lambda directory, names: [name for name in names if Path(directory) == prepared["home"]
                                                             and name in ("auth.json", "config.toml")])
            isolation["task_state"] = "retained_for_same_task"
        else:
            isolation["task_state"] = "discarded"
        self._discard(prepared)
        return scrubber.scrub({**value, "isolation": isolation})

    def _bind_hooks(self, prepared, workspace, scrubber, admission) -> dict:
        """S3b discover-then-bind, in its own owned container of the same profile, mounts and credential
        copy: the App Server with the hook set configured and no trust state lists the hooks (no turn, no
        model); the peer-reported hash of exactly this set's entries becomes the trust state the run's
        container starts with. The discovery container follows the one lifecycle rule; if its stop cannot
        be confirmed the run's record is left unresolved, so its credential copy stays unsettled.

        Fix F1 (S3 round 1): before the discovery container can exist, its durable run record is bound as a
        dependent of the issued credential copy (credentials ledger) and of the run's record (`dependents`):
        settlement, the broker's reconcile and the parent's reconcile all refuse until the discovery record
        proves its own container and client gone. A discovery container that is not removed refuses the run."""
        hook_set = prepared["hooks"]
        run_id = uuid4().hex
        directory = self.root / run_id
        directory.mkdir(parents=True)
        container = OwnedContainer(self.config, self.docker, run_id, "codex", runner=self.host.runner)
        record = new_record(directory, role="codex", workspace=workspace, config=self.config, container=container,
                            profile=self.role_profile, purpose="native_hook_discovery", parent=self.container.run_id)
        # Durable before anything is created: the child's own record, then the two bindings (fix F1).
        advance(record, "prepared", purpose="native_hook_discovery")
        admission.bind_dependent(record["record"])
        self.record["dependents"] = [record["record"]]
        self._advance("hook_discovery_bound", discovery=record["record"])
        probe = AppServer(executable=CODEX_EXECUTABLE, context_window=self.context_window,
                          hooks=hook_set.configuration)
        args = container_args(self.config, name=container.name, run_id=run_id, role="codex", network=self.network,
                              mounts=prepared["mounts"], environment=codex_environment(), pass_names=(),
                              entry=[CODEX_EXECUTABLE, *probe.server_arguments()], workdir=WORKSPACE,
                              user=host_user())
        try:
            container_id = container.create(args, docker_environment(self.environment_source))
        except IsolationError:
            advance(record, "refused", reason="container_create_failed")
            raise
        record["container"] = container_id
        try:
            advance(record, "created", container=container_id)
            container.verify(prepared["expected"], self.network)
        except IsolationError as exc:
            removal = container.remove()
            advance(record, "refused" if removal["removed"] else "created", reason=exc.reason_code)
            raise
        trees = []

        def discover():
            trees.append(self.host.trees.spawn([self.docker, "start", "--attach", "--interactive", container.id],
                                               env=docker_environment(self.environment_source),
                                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            advance(record, "running", client_pid=trees[0].process.pid)
            server = AttachedAppServer(trees[0].process, WORKSPACE)
            server.hooks = hook_set.configuration
            with server:
                try:
                    rows = server.request("hooks/list", {"cwds": [WORKSPACE]}, 30)["data"]
                except Exception as exc:
                    replaced = scrubber.failure(exc)
                    if replaced is exc:
                        raise
                    raise replaced from None
            return bound_state(rows, hook_set)

        def end_client():
            if not trees:
                return {"confirmed": True}
            ended = trees[0].terminate("container_stopped")
            trees[0].close()
            return ended
        try:
            state, stopped = hold(container, record, discover, client=end_client,
                                  detail=lambda value: {"hooks": {"bound": len(value), "digests": list(hook_set.digests)}},
                                  observer=self.observer)
        except BaseException:
            if cleanup_debt(record) is not None:
                self._advance("hook_discovery_unconfirmed", discovery=str(directory / "run.json"))
            raise
        if not stopped["confirmed"]:
            self._advance("hook_discovery_unconfirmed", discovery=str(directory / "run.json"))
            raise ContractError("Codex hook discovery container termination could not be confirmed; recovery record "
                                + str(directory / "run.json"))
        removal = retire(container, record, {"hooks_bound": sorted(state)}, "hooks_bound", observer=self.observer)
        if not removal.get("removed"):
            raise ContractError("Codex hook discovery container could not be removed; the run's credential copy stays "
                                "unsettled; recovery record " + str(directory / "run.json"))
        return state

    def _after_stop(self, admission, prepared) -> dict:
        """After a confirmed stop and before removal: the read-only configuration must be byte-for-byte
        what was mounted, then the credential copy is settled. Either anomaly is a hold."""
        config = prepared["config"]
        try:
            observed = hashlib.sha256(config.read_bytes()).hexdigest()
        except OSError:
            observed = None
        if observed != CODEX_CONFIG_SHA256:
            admission.broker._quarantine(admission.entry, "config_digest_changed")
            raise IsolationError("codex_credential_quarantined", "config_digest_changed")
        return admission.settle()

    def _settle_quietly(self, admission) -> None:
        """A refusal before any run container started: the untouched copy settles as unchanged. A copy with a
        dependent hook-discovery container not proven gone is refused by the broker and stays issued (S3b)."""
        if admission.entry is None or admission.entry.get("state") != "issued":
            return
        try:
            admission.settle()
        except IsolationError:
            pass

    @staticmethod
    def _discard(prepared) -> None:
        """This run's own home (with its credential copy) and hand-off copy; records stay."""
        if not prepared:
            return
        for key in ("home", "handoff_path"):
            if prepared.get(key) is not None:
                discard_tree(prepared[key])


class IsolatedWorker:
    """What composition hands the executor: the validated selection, where its runs live and the
    injected host facilities. (The verifier inspectors move with evidence, S8.)

    `observer` (S10 F2, class default None; `composition.operation.build_executor` sets it to the executor's process
    observer): handed to every runtime this worker builds, so their `hold`/`retire` emit `operations.cleanup_recorded`."""

    observer = None

    def __init__(self, config: dict, root, docker: str = "docker", *, host: ContainerHost,
                 broker_factory=None, credentials: CredentialBoundary | None = None):
        self.config, self.root, self.docker, self.host = config, Path(root), docker, host
        self.broker_factory, self.credentials = broker_factory, credentials

    # S10 GAP #6 (OWNER-DECISIONS-S10 #6): RunTask's isolation collaborator; M7's Executor called the same
    # functions with `isolation.config`.
    def summary(self) -> dict:
        return summary(self.config)  # the module-level container_spec.summary, not this method

    def review_context(self, cwd, profile: str | None = None) -> dict:
        return isolated_review_context(cwd, self.config, profile)

    def runtime(self, *, model, runtime, max_budget_usd, settings_document,
                project_delivery=None, profile: str = "claude-impl-rw", handoff=None) -> IsolatedClaudeRuntime:
        built = IsolatedClaudeRuntime(self.config, self.root / "runs", model=model, runtime=runtime,
                                      max_budget_usd=max_budget_usd, settings_document=settings_document,
                                      docker=self.docker, watch=(self.root / "replays",),
                                      project_delivery=project_delivery, profile=profile, handoff=handoff,
                                      host=self.host)
        if self.observer is not None:
            built.observer = self.observer
        return built

    def codex_runtime(self, *, profile: str, context_window=None, handoff=None, native_hooks=None):
        """INV-ROLE-CONTAINER-001 / INV-CODEX-CREDENTIAL-001: the Codex App Server inside a
        codex-role-ro or codex-impl-rw container, with this selection's credential broker. S4 wiring:
        `native_hooks(destination)` (execution.adapters.transports) builds the run's bound hook set."""
        require(self.config.get("codex") is not None, "Codex role containers need ZEUS_CODEX_CREDENTIAL_STORE")
        require(self.broker_factory is not None and self.credentials is not None,
                "Codex role containers need the credentials boundary")
        built = IsolatedCodexRuntime(self.config, self.root / "runs", profile=profile,
                                     broker=self.broker_factory(self.config["codex"]["credential_store"]),
                                     docker=self.docker, watch=(self.root / "replays",), context_window=context_window,
                                     handoff=handoff, state_root=self.root / "codex-state", host=self.host,
                                     credentials=self.credentials, native_hooks=native_hooks)
        if self.observer is not None:
            built.observer = self.observer
        return built

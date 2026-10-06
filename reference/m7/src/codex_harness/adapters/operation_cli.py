"""`zeus operate run|status`: thin wiring of real services around the application state machine."""
from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from codex_harness.adapters.commands import no_console_kwargs
from codex_harness.adapters.providers import ExecutionPolicy, packaged_policy
from codex_harness.application.operation import Operation, OperationRefused, identity_digest
from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.operation import (
    RESTRICTED,
    WORKER_PROFILE,
    goal_binding,
    provider_settings,
    validate_manifest,
)
from codex_harness.domain.policy import POLICY
from codex_harness.domain.providers import parse_configuration

MAX_MANIFEST_BYTES = 256 * 1024


def read_document(path: Path, label: str) -> dict:
    """Bounded UTF-8 JSON with duplicate keys refused; errors name the file role, not its content.
    utf-8-sig drops one optional leading BOM from operator-authored files: the raw byte budget still
    counts it, interior U+FEFF stays data, and malformed UTF-8 or UTF-16 remains refused."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, label + " has a duplicate JSON key")
            result[key] = value
        return result
    try:
        require(path.stat().st_size <= MAX_MANIFEST_BYTES, label + " exceeds budget")
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    except OSError as exc:
        raise ContractError(label + " unavailable") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ContractError(label + " is not valid JSON") from exc


def read_manifest(path: Path) -> dict:
    return read_document(path, "Operation manifest")


class GitSource:
    """Read pinned bytes with git argv, never a shell."""

    def __init__(self, repository):
        self.repository = str(repository)

    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", self.repository, *args], capture_output=True, timeout=60,
                              **no_console_kwargs())

    def commit_exists(self, revision: str) -> bool:
        return self._run("cat-file", "-e", revision + "^{commit}").returncode == 0

    def blob(self, revision: str, path: str) -> tuple[str | None, bytes]:
        listing = self._run("ls-tree", "-z", revision, "--", path)
        entries = [e for e in listing.stdout.split(b"\0") if e]
        if listing.returncode or len(entries) != 1:
            return None, b""
        mode = entries[0].split(b" ", 1)[0].decode("ascii")
        shown = self._run("show", revision + ":" + path)
        return (mode if shown.returncode == 0 else None), shown.stdout


def bind_goal(manifest: dict, source) -> dict:
    if not source.commit_exists(manifest["base_revision"]):
        raise OperationRefused("base_revision_missing")
    mode, data = source.blob(manifest["base_revision"], manifest["goal"]["path"])
    if mode is None:
        raise OperationRefused("goal_missing_at_base")
    return goal_binding(manifest, mode, data)


def execution_policy(manifest: dict, host_settings: dict) -> ExecutionPolicy:
    """The packaged policy with the fixed worker profile and restricted surface, enabled for this
    operation's controls; executable, credentials and endpoints stay host settings."""
    policy = packaged_policy()
    claude = policy.provider("claude")
    runtime = {**claude.runtime, "worker_profile": WORKER_PROFILE, "restricted": RESTRICTED}
    policy = replace(policy, providers={**policy.providers, "claude": replace(claude, runtime=runtime)})
    merged = {**host_settings, **provider_settings(manifest)}
    return ExecutionPolicy(policy, parse_configuration(policy, merged))


def identity(manifest: dict, repository, policy: ExecutionPolicy, host_settings: dict, runtime,
             evidence_profile: dict | None = None, isolation: dict | None = None) -> dict:
    """Effective repository, resolved runtime directory, packaged policy, provider policy/config and
    endpoint digests; a same-id run under any other of these is refused before any call. With a host
    project evidence profile its digest is bound too (INV-PROJECT-EVIDENCE-001), so a same-id replay
    cannot change its verification context; without one the identity keeps its exact old shape.
    A host-selected isolation (INV-ISOLATED-WORKER-001) binds its mode, image and limits the same way."""
    summary = policy.summary()
    profiled = {} if evidence_profile is None else {"evidence_profile": evidence_profile["profile_digest"]}
    if isolation is not None:
        profiled["isolation"] = {"mode": isolation["mode"], "image": isolation["image"],
                                 "limits": isolation["limits"], "digest": isolation["digest"]}
    return {**profiled, "repository": digest(str(Path(repository).resolve())),
            "runtime": digest(str(Path(runtime).resolve())),
            "runtime_policy": digest(POLICY.snapshot()),
            "provider": {"policy_digest": summary["policy_digest"], "config_digest": summary["config_digest"],
                         "worker_profile": WORKER_PROFILE, "restricted": RESTRICTED},
            "endpoints": identity_digest({"database": host_settings.get("HARNESS_DATABASE_URL", ""),
                                          "redis": host_settings.get("HARNESS_REDIS_URL", ""),
                                          "namespace": host_settings.get("HARNESS_REDIS_NAMESPACE", "")})}


def session_owner(service, operation_id: str, observer=None) -> dict:
    """INV-CONTINUATION-001 / INV-WORKER-SESSION-001: the `worker_sessions` keyword for the executor
    when, and only when, the lane store holds the opt-in controller's binding naming a task session
    for this operation. Everything else keeps the exact legacy fresh path (an empty keyword set)."""
    from codex_harness.domain.continuation import validate_binding

    with service.store.transaction() as tx:
        binding = tx.get("continuation_bindings", operation_id)
    if binding is None or validate_binding(binding)["session"] is None:
        return {}
    from codex_harness.adapters.worker_sessions import SessionArchives, archive_root, evidence_store
    from codex_harness.application.worker_sessions import WorkerSessions

    return {"worker_sessions": WorkerSessions(service.store, SessionArchives(archive_root()),
                                              evidence=evidence_store(), observer=observer)}


def run(service, args) -> dict:
    from codex_harness.adapters.bus import RedisBus
    from codex_harness.adapters.call_budget import CallBudget
    from codex_harness.adapters.configuration import repository_root, runtime_dir, settings
    from codex_harness.adapters.project_evidence import load_profile
    from codex_harness.application.workflow import Workflow
    from codex_harness.bootstrap import (
        build_collector,
        build_executor,
        build_observer,
        host_isolation,
        redis_url,
    )

    document = read_manifest(args.file)
    manifest = validate_manifest(document, packaged_policy())
    host = settings()
    policy = execution_policy(manifest, host)
    # Loaded once from host settings; an invalid configured profile refuses here, before any provider.
    profile = load_profile(host)
    # INV-ISOLATED-WORKER-001: the host selection (or None) is validated, with Docker, image and token,
    # before the reservation, the executor and any provider; a refusal here never runs on the host.
    isolated = host_isolation(profile)
    repository = repository_root()
    goal = bind_goal(manifest, GitSource(repository))
    bound = identity(manifest, repository, policy, host, runtime_dir(), profile,
                     **({} if isolated is None else {"isolation": isolated.config}))
    observer = build_observer(service.store, "cli.operate")
    try:
        # No knowledge adapter: this entry point writes execution ledgers and provisional
        # artifacts only; formal knowledge promotion is a separate explicit contract.
        executor = build_executor(service, observer=observer, execution_policy=policy, knowledge=False,
                                  evidence_profile=profile, **({} if isolated is None else {"isolation": isolated}),
                                  **session_owner(service, manifest["id"], observer))
        # INV-OBSERVATION-001: the one process observer also sees the operation's message path.
        operation = Operation(service, executor, RedisBus(redis_url()), Workflow(service.store, service.org),
                              CallBudget(), build_collector(service.store, observer), observer=observer)
        return operation.run(manifest, bound, goal)
    finally:
        observer.close()


def status(service, args) -> dict:
    # Store read only: no executor, observer, bus or provider is built.
    return Operation(service).status(args.operation_id)


def refusal(exc: Exception) -> dict:
    """What the CLI prints for a failure: a code and a type, never the raw text or a value."""
    code = getattr(exc, "reason_code", None)
    if code is None and isinstance(exc, ContractError):
        code = "contract_refused"
    return {"status": "refused", "reason_code": code or "error", "error_type": type(exc).__name__, "exit_code": 1}

"""`zeus continuation register|tick|status|identity|conduct` (INV-CONTINUATION-001).

`register`, `tick`, `status` and `identity` run against the Fleet control store; `conduct` is the
lane-side child the controller launches (it is also the owner's manual command for one accepted
operation). Refusals print a code and a type, never a manifest, a path, a DSN or a raw exception.
"""
from __future__ import annotations

from pathlib import Path

from codex_harness.adapters.operation_cli import execution_policy, read_manifest
from codex_harness.adapters.providers import packaged_policy
from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.operation import correlation_id, validate_manifest

__all__ = ["add_parser", "conduct", "execute", "refusal"]


def add_parser(commands) -> None:
    root = commands.add_parser("continuation", help="Opt-in conductor continuation over finite operations")
    sub = root.add_subparsers(dest="continuation_command", required=True)
    register = sub.add_parser("register", help="Register one owner policy read at a commit (urn:zeus:continuation-policy:1)")
    register.add_argument("--lane", required=True, help="Lane whose repository holds the policy")
    register.add_argument("--revision", required=True, help="40-hex commit the policy is read at")
    register.add_argument("--path", required=True, help="Repository-relative policy path")
    tick = sub.add_parser("tick", help="One bounded continuation pass; no model call when idle")
    tick.add_argument("--policy", required=True)
    status = sub.add_parser("status", help="Read the continuation projection; store read only")
    status.add_argument("--policy", default=None)
    identity = sub.add_parser("identity", help="Print a lane's session archive identity for authoring the policy")
    identity.add_argument("--lane", required=True)
    conduct = sub.add_parser("conduct", help="Lane side: the guarded conductor review of one accepted operation")
    conduct.add_argument("--file", type=Path, required=True, help="The operation's frozen manifest JSON")


def _config(service) -> dict:
    from codex_harness.application.fleet import Fleet
    return Fleet(service.store).registered()["config"]


def conduct(service, args, *, executor=None, budget=None, sessions=None) -> dict:
    """The existing guarded `decide_one("conductor", expected=...)` for exactly this operation.

    The lead's `review.result` intent for the conductor is taken from the operation's own outbox
    row and handled by the existing Workflow (idempotent by its inbox hash), which creates the
    pending `review_conductor` row. The decision itself is reserved on the machine ledger and
    claimed only if it is still that exact pending row; a second dispatcher claims nothing."""
    from codex_harness.application.operation import BudgetedExecutor
    from codex_harness.application.workflow import Workflow

    manifest = validate_manifest(read_manifest(args.file), packaged_policy())
    correlation = correlation_id(manifest)
    with service.store.transaction() as tx:
        operation = tx.get("operations", manifest["id"])
        require(operation is not None and operation.get("status") == "accepted"
                and operation.get("manifest_sha256") == digest(manifest), "Operation is not the accepted one named")
        lead = operation.get("decision_id")
        messages = [row["message"] for row in tx.scan("outbox")
                    if (row.get("message") or {}).get("type") == "review.result"
                    and row["message"].get("correlation_id") == correlation
                    and row["message"]["who"]["recipient"] == "conductor"
                    and row["message"]["what"]["details"].get("decision_id") == lead]
        binding = tx.get("continuation_bindings", manifest["id"])
    require(len(messages) == 1, "Conductor review intent missing")
    message = messages[0]
    Workflow(service.store, service.org).handle(message)
    expected = {"id": message["message_id"], "correlation_id": correlation, "statuses": {"pending", "retry"}}
    if executor is None:
        executor, budget, sessions = _lane_executor(service, manifest, binding)
    wrapped = BudgetedExecutor(executor, budget, manifest["budget"], "continuation:" + manifest["id"],
                               manifest["claude"]["model"])
    result = wrapped.decide_one("conductor", expected=expected)
    with service.store.transaction() as tx:
        decision = tx.get("decisions_pending", message["message_id"]) or {}
    session = (binding or {}).get("session") if isinstance(binding, dict) else None
    if sessions is not None and decision.get("status") == "succeeded" and isinstance(session, dict):
        try:
            sessions.record_review(session["task_id"], decision["id"])
        except ContractError:
            pass  # the controller records the same decision idempotently on its next tick
    accepted = (decision.get("result") or {}).get("accepted")
    return {"decision_id": message["message_id"], "claimed": result is not None, "status": decision.get("status"),
            "accepted": accepted if isinstance(accepted, bool) else None,
            "calls": {"reserved": len(wrapped.slots), "settled": sum(s["settled"] for s in wrapped.slots)},
            "exit_code": 0 if decision.get("status") == "succeeded" else 1}


def _lane_executor(service, manifest, binding):
    from codex_harness.adapters.call_budget import CallBudget
    from codex_harness.adapters.configuration import settings
    from codex_harness.adapters.operation_cli import session_owner
    from codex_harness.adapters.project_evidence import load_profile
    from codex_harness.bootstrap import build_executor, build_observer, host_isolation

    host = settings()
    profile = load_profile(host)
    isolated = host_isolation(profile)
    observer = build_observer(service.store, "cli.continuation")
    owner = session_owner(service, manifest["id"], observer)
    executor = build_executor(service, observer=observer, execution_policy=execution_policy(manifest, host),
                              knowledge=False, evidence_profile=profile,
                              **({} if isolated is None else {"isolation": isolated}), **owner)
    return executor, CallBudget(), owner.get("worker_sessions")


def execute(service, args) -> dict:
    from codex_harness.adapters import continuation as adapter
    from codex_harness.application.continuation import Continuation

    command = args.continuation_command
    if command == "status":
        return {**Continuation(service.store).status(args.policy), "exit_code": 0}
    if command == "conduct":
        return conduct(service, args)
    config = _config(service)
    if command == "identity":
        from codex_harness.domain.fleet import lane_of, repository_identity
        lane = lane_of(config, args.lane)
        return {"lane": args.lane, "repository": repository_identity(lane["repository"]),
                "session_archive_sha256": adapter.archive_identity(lane["runtime"]), "exit_code": 0}
    if command == "register":
        return {**adapter.register_policy(service.store, config, args.lane, args.revision, args.path), "exit_code": 0}
    from codex_harness.adapters.configuration import settings
    from codex_harness.bootstrap import build_observer
    observer = build_observer(service.store, "cli.continuation")
    try:
        # One owned pass: a conductor child it starts is this process's until it ends (never an
        # orphan of a returned command), then its outcome is settled by one drain.
        tick = adapter.ContinuationPass(service.store, config, settings(), args.policy, observer=observer)
        result = tick()
        if tick.owned():
            tick.processes.join()
            drained = tick.drain()
            result = {**result, "actions": result["actions"] + drained["actions"],
                      "skipped": result["skipped"] + drained["skipped"]}
    finally:
        observer.close()
    return {**result, "exit_code": 1 if result["outcome"] == "refused" else 0}


def refusal(exc: Exception) -> dict:
    return {"status": "refused", "reason_code": getattr(exc, "reason_code", None) or
            ("contract_refused" if isinstance(exc, ContractError) else "error"),
            "next_owner": getattr(exc, "owner", None), "error_type": type(exc).__name__, "exit_code": 1}

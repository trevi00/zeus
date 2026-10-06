"""The `zeus continuation` root: the argument parser and the command bodies (M7 adapters/continuation_cli.py, cli.py continuation_command).

Layer: entry
Owns: add_parser (the argument shape of `zeus continuation`), run (its body: M7 continuation_command) and the private _config, _conduct, _execute and _refusal (M7 continuation_cli)
Does not own: dispatch (entry.cli main), the policy, lane and process wiring (composition.continuation) and the lane executor (composition.cli_continuation)
Entry points: add_parser, run
Contracts: INV-CONTINUATION-001

Moved from M7 adapters/continuation_cli.py:30-62 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
`run` is M7 `cli.py` `continuation_command` (:536-547) and `_config`, `_conduct`, `_execute` and `_refusal` are `adapters/continuation_cli.py` `_config` (:65-67), `conduct` (:70-114), `execute` (:135-185) and
`refusal` (:188-191) (R-c27, S10 unit C8b-1): the bodies are M7's verbatim except that the service is built first (as M7 `main()` did), `Fleet(store).registered()` is `FleetRegistry(store).registered()`, `Workflow(...).handle`
is the `MessageHandler` of `composition.cli.messages`, `read_manifest` is `entry.cli.operation`'s, `packaged_policy` is `composition.cli_operation`'s, `_lane_executor` is `composition.cli_continuation.lane_executor`, the
`adapter.*` calls are `composition.continuation` and `Continuation(store).status` is `PolicyFrames.status` (owner `frames` of `composition.continuation.continuation_owners`). `_conduct` stays here because it reads the
manifest through `entry.cli.operation`, which composition may not import. Imports sit inside the functions, so importing this module stays light.
"""

from pathlib import Path


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
    research = sub.add_parser("research-accept", help="Owner: record one scoped research receipt "
                              "(urn:zeus:continuation-research-receipt:1, or :2 for a mixed-cause family) for an "
                              "exact research intent")
    research.add_argument("--file", type=Path, required=True, help="The owner's receipt JSON")
    supplement = sub.add_parser("research-supplement", help="Owner: record one typed research scope supplement "
                                "(urn:zeus:continuation-research-scope-supplement:1); releases nothing by itself")
    supplement.add_argument("--file", type=Path, required=True, help="The owner's supplement JSON")
    ownership = sub.add_parser("ownership-reconcile", help="Owner: bind one admitted continuation successor to its "
                               "origin's Portfolio target through the persisted intent lineage")
    ownership.add_argument("--intent", required=True, help="The successor's continuation intent id")
    capacity = sub.add_parser("capacity-grant", help="Owner: one-use capacity for ONE exact evidence_repair intent "
                              "refused for correction_budget_exhausted (urn:zeus:continuation-capacity-grant:1); "
                              "the budget itself never grows")
    capacity.add_argument("--file", type=Path, required=True, help="The owner's grant JSON")
    requalify = sub.add_parser("delivery-requalify", help="Owner: supersede ONE delivery intent whose plan was "
                               "withdrawn by one fresh operation on the current main "
                               "(urn:zeus:continuation-delivery-requalification:1); never automatic")
    requalify.add_argument("--file", type=Path, required=True, help="The owner's requalification JSON")


def run(args) -> None:
    """INV-CONTINUATION-001: exit 0 only for a completed command; refusals print a code, the named
    next owner and a type, never a manifest, a path, a DSN or a raw exception."""
    from codex_harness.composition import build
    from codex_harness.entry.cli.output import emit
    service = build()
    try:
        result = _execute(service, args)
    except Exception as exc:
        emit(_refusal(exc))
        raise SystemExit(1) from exc
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def _config(service) -> dict:
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    return FleetRegistry(service.store).registered()["config"]


def _conduct(service, args, *, executor=None, budget=None, sessions=None) -> dict:
    """The existing guarded `decide_one("conductor", expected=...)` for exactly this operation.

    The lead's `review.result` intent for the conductor is taken from the operation's own outbox
    row and handled by the existing Workflow (idempotent by its inbox hash), which creates the
    pending `review_conductor` row. The decision itself is reserved on the machine ledger and
    claimed only if it is still that exact pending row; a second dispatcher claims nothing."""
    from codex_harness.composition import cli, cli_continuation
    from codex_harness.composition.cli_operation import packaged_policy
    from codex_harness.coordination.application.operation import BudgetedExecutor
    from codex_harness.coordination.domain.operation import correlation_id, validate_manifest
    from codex_harness.entry.cli.operation import read_manifest
    from codex_harness.kernel.errors import ContractError, require
    from codex_harness.kernel.ids import digest

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
    cli.messages(service).handle(message)
    expected = {"id": message["message_id"], "correlation_id": correlation, "statuses": {"pending", "retry"}}
    if executor is None:
        executor, budget, sessions = cli_continuation.lane_executor(service, manifest, binding)
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


def _execute(service, args) -> dict:
    from codex_harness.composition import continuation as adapter

    command = args.continuation_command
    if command == "status":
        return {**adapter.continuation_owners(service.store).frames.status(args.policy), "exit_code": 0}
    if command == "conduct":
        return _conduct(service, args)
    if command == "ownership-reconcile":
        return {**adapter.reconcile_ownership(service.store, args.intent), "exit_code": 0}
    config = _config(service)
    if command == "identity":
        from codex_harness.coordination.domain.fleet import lane_of, repository_identity
        lane = lane_of(config, args.lane)
        return {"lane": args.lane, "repository": repository_identity(lane["repository"]),
                "session_archive_sha256": adapter.archive_identity(lane["runtime"]), "exit_code": 0}
    if command == "register":
        return {**adapter.register_policy(service.store, config, args.lane, args.revision, args.path), "exit_code": 0}
    if command == "research-accept":
        from codex_harness.composition.configuration import settings
        return {**adapter.accept_research(service.store, config, settings(), adapter.read_receipt(args.file)),
                "exit_code": 0}
    if command == "research-supplement":
        from codex_harness.composition.configuration import settings
        return {**adapter.supplement_research(service.store, config, settings(), adapter.read_receipt(args.file)),
                "exit_code": 0}
    if command == "capacity-grant":
        from codex_harness.composition.configuration import settings
        return {**adapter.grant_capacity(service.store, config, settings(), adapter.read_grant(args.file)),
                "exit_code": 0}
    if command == "delivery-requalify":
        from codex_harness.composition.configuration import settings
        return {**adapter.requalify_delivery(service.store, config, settings(),
                                             adapter.read_requalification(args.file)), "exit_code": 0}
    from codex_harness.composition.configuration import settings
    from codex_harness.composition.observation import build_observer
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


def _refusal(exc: Exception) -> dict:
    from codex_harness.kernel.errors import ContractError
    return {"status": "refused", "reason_code": getattr(exc, "reason_code", None) or
            ("contract_refused" if isinstance(exc, ContractError) else "error"),
            "next_owner": getattr(exc, "owner", None), "error_type": type(exc).__name__, "exit_code": 1}

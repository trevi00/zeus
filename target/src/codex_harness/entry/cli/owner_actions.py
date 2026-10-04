"""The `zeus owner-actions` root: the argument parser and the command bodies (M7 adapters/owner_actions.py, cli.py owner_actions_command).

Layer: entry
Owns: add_parser (the argument shape of `zeus owner-actions`), run (its body: M7 owner_actions_command) and the private _execute and _refusal (M7 execute and refusal)
Does not own: dispatch (entry.cli main), the policy load, the coordinator, the tick and run loop and the guarded assessment (composition.owner_actions)
Entry points: add_parser, run
Contracts: INV-HOST-DELIVERY-FIRST-ACTIVATION-001, INV-OWNER-ACTIONS-001, INV-OWNER-ACTIONS-MIGRATION-001

Moved from M7 adapters/owner_actions.py:509-537 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
`run` is M7 `cli.py` `owner_actions_command` (:550-561) and `_execute` and `_refusal` are `adapters/owner_actions.py` `execute` (:540-577) and `refusal` (:580-583) (R-c32, S10 unit C8b-3): the bodies are M7's verbatim except that the service is built first (as M7
`main()` did), `OwnerActions(store).status` is `composition.owner_actions.owner_action_owners(store).scheduler.status`, `owner.request_migration` and `owner.recover_canary` are the `migration` and `canary` owners' (that module's table), `Fleet(store).registered()` is
`FleetRegistry` and every composition function (`assess`, `register_policy`, `coordinator`, `tick_policy`, `policy_list`, `run_loop`) is looked up through that module at call time. Imports sit inside the functions, so importing this module stays light.
"""

import json
from pathlib import Path


def add_parser(commands) -> None:
    root = commands.add_parser("owner-actions", help="Server-owned research acceptance, delivery-plan and canary "
                                                     "handoffs (opt-in; approves nothing itself)")
    sub = root.add_subparsers(dest="owner_actions_command", required=True)
    register = sub.add_parser("register", help="Register the owner policy read at a commit "
                                               "(urn:zeus:owner-actions-policy:1 or :2)")
    register.add_argument("--lane", required=True)
    register.add_argument("--revision", required=True)
    register.add_argument("--path", required=True)
    tick = sub.add_parser("tick", help="One bounded pass; no model call and no write when idle")
    tick.add_argument("--policy", required=True)
    run = sub.add_parser("run", help="Gated wakeup loop over `tick` of every named policy in turn")
    run.add_argument("--policy", required=True, action="append",
                     help="A registered owner policy id; repeat it to tick several in this one process")
    run.add_argument("--interval", type=int, default=15)
    run.add_argument("--max-ticks", type=int, default=0, dest="max_ticks")
    status = sub.add_parser("status", help="Read the owner-action projection; store read only")
    status.add_argument("--policy", default=None)
    migrate = sub.add_parser("migrate", help="Record ONE owner-approved evaluator migration of a check-rejected "
                                             "merged release (INV-OWNER-ACTIONS-MIGRATION-001); tick advances it")
    migrate.add_argument("--document", required=True, help="JSON migration document (exact keys)")
    # INV-OWNER-ACTIONS-001 x INV-HOST-DELIVERY-FIRST-ACTIVATION-001: the typed owner canary recovery.
    recover = sub.add_parser("canary-recover", help="Return ONE halted owner canary to its SAME queued job after "
                             "the lane consumption retry (exact document and its sha256 evidence)")
    recover.add_argument("--document", required=True, help="JSON owner canary-recovery document (exact keys)")
    recover.add_argument("--evidence", required=True, help="sha256:<digest of the document>")
    assess_parser = sub.add_parser("assess", help="Guardian child: the guarded independent assessment of one row")
    assess_parser.add_argument("--decision", required=True)
    assess_parser.add_argument("--correlation", required=True)


def run(args) -> None:
    """INV-OWNER-ACTIONS-001: exit 0 only for a completed command; refusals print a code and a type,
    never a receipt, a plan, a report, a path, a DSN or a raw exception."""
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


def _execute(service, args) -> dict:
    from codex_harness.composition import owner_actions as composition
    from codex_harness.composition.configuration import settings
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.domain.owner_actions import OwnerActionRefused

    command = args.owner_actions_command
    if command == "status":
        return {**composition.owner_action_owners(service.store).scheduler.status(args.policy), "exit_code": 0}
    if command == "assess":
        with service.store.transaction() as tx:
            decision = tx.get("decisions_pending", args.decision) or {}
            policies = tx.scan("owner_action_policies")
        label = next((row["policy"]["assessment"]["model_label"] for row in policies), "owner-assessment")
        if decision.get("phase") != "owner_assessment":
            raise OwnerActionRefused("assessment_row_foreign", "decision")
        return composition.assess(service, args.decision, args.correlation, label)
    config = FleetRegistry(service.store).registered()["config"]
    if command == "register":
        return {**composition.register_policy(service.store, config, args.lane, args.revision, args.path),
                "exit_code": 0}
    owner = composition.coordinator(service, config, settings())
    if command == "migrate":
        try:
            document = json.loads(Path(args.document).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise OwnerActionRefused("migration_document_unreadable", "document") from exc
        return {**owner.migration.request_migration(document), "exit_code": 0}
    if command == "canary-recover":
        try:
            document = json.loads(Path(args.document).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise OwnerActionRefused("canary_recovery_document_unreadable", "document") from exc
        return {**owner.canary.recover_canary(document, args.evidence), "exit_code": 0}
    if command == "tick":
        result = composition.tick_policy(owner, config, args.policy)
        owner.assessments.join()
        return {**result, "exit_code": 1 if result["outcome"] == "refused" else 0}
    policies = composition.policy_list(args.policy)
    return {**composition.run_loop(lambda: composition.tick_policies(owner, config, policies), interval=args.interval,
                                   max_ticks=args.max_ticks), "policies": policies, "exit_code": 0}


def _refusal(exc: Exception) -> dict:
    from codex_harness.kernel.errors import ContractError

    return {"status": "refused", "reason_code": getattr(exc, "reason_code", None)
            or ("contract_refused" if isinstance(exc, ContractError) else "error"),
            "error_type": type(exc).__name__, "exit_code": 1}

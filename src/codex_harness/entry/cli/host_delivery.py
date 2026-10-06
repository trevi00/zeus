"""The `zeus host-delivery` root: the argument parser and the command bodies (M7 adapters/host_delivery.py, cli.py host_delivery_command).

Layer: entry
Owns: add_parser (the argument shape of `zeus host-delivery`), run (its body: M7 host_delivery_command) and the private _execute and _refusal (M7 execute and refusal)
Does not own: dispatch (entry.cli main), the coordinator, the lane routing and the run loop (composition.cli_host_delivery)
Entry points: add_parser, run
Contracts: INV-HOST-DELIVERY-001, INV-HOST-DELIVERY-FIRST-ACTIVATION-001

Moved from M7 adapters/host_delivery.py:1096-1137 and LANE_HELP at adapters/host_delivery.py:1092-1093 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
`run` is M7 `cli.py` `host_delivery_command` (:510-521) and `_execute` and `_refusal` are `adapters/host_delivery.py` `execute` (:1290-1345) and `refusal` (:1140-1146) (R-c31, S10 unit C8b-4): the bodies are M7's verbatim except that the service is built first (as M7
`main()` did), each `HostDelivery(store, org, ...)` is `composition.cli_host_delivery.host_delivery_owners` and each method call is routed to the S7 split owner that module's table names (`registry`, `controller`, `withdrawal`, `resumption`, `recovery`),
`load_plan(GitSource(repository), ...)` is `composition.cli_host_delivery.load_plan(repository, ...)`, and every composition function (`resolve_lane`, `controller`, `lane_git`, `_git`, `_observer`, `_lane_observer`, `_settings`, `run_loop`) is looked up through that module at call
time. The two JSON files are read as M7 read them (`register-targets` with `json.loads`, the `resume` document with the bounded `read_json`, a refusal for an unreadable one): `entry.cli.operation.read_document` would change both refusals' codes and types, which the
SOURCE golden of `entry.cli_host_delivery.pg` pins. Imports sit inside the functions, so importing this module stays light.
"""

import json
from pathlib import Path

from codex_harness.delivery.domain.host_delivery import WITHDRAW_REASONS

LANE_HELP = ("One registered Fleet lane whose store, repository and runtime own this delivery; "
             "omitted keeps the control store. The Fleet activation gate stays the control store's")


def add_parser(commands) -> None:
    delivery = commands.add_parser("host-delivery",
                                   help="Durable delivery of a reviewed release to a host target; "
                                        "opt-in, reuses Releases approval and the ReleaseQueue fence")
    sub = delivery.add_subparsers(dest="delivery_command", required=True)
    targets = sub.add_parser("register-targets",
                             help="Register the owner's authorized host target registry "
                                  "(urn:zeus:host-delivery-targets:1); host configuration only")
    targets.add_argument("--file", type=Path, required=True)
    register = sub.add_parser("register", help="Register one owner-approved plan read at a commit")
    register.add_argument("--revision", required=True, help="40-hex commit the plan is read at")
    register.add_argument("--path", required=True, help="Repository-relative plan path")
    tick = sub.add_parser("tick", help="Advance at most one delivery by at most one stage")
    tick.add_argument("--plan", default=None, help="One registered plan id; omitted selects one")
    run_command = sub.add_parser("run", help="Bounded tick loop; an empty queue idles without "
                                             "provider calls")
    run_command.add_argument("--once", action="store_true", help="One tick, then exit")
    run_command.add_argument("--interval", type=int, default=15, help="Seconds between ticks")
    run_command.add_argument("--max-ticks", type=int, default=0, dest="max_ticks",
                             help="Stop after this many ticks; 0 runs until stopped")
    status = sub.add_parser("status", help="Read the delivery projection; store read only")
    status.add_argument("--plan", default=None, help="One plan id; omitted reads every plan")
    withdraw = sub.add_parser("withdraw", help="Owner: retire one delivery the host never reached, on "
                                               "staleness observed now; plan, request and PR are kept")
    withdraw.add_argument("--plan", required=True, help="The registered plan id")
    withdraw.add_argument("--plan-sha256", required=True, dest="plan_sha256",
                          help="The registered plan digest (from status)")
    withdraw.add_argument("--reason", required=True, choices=WITHDRAW_REASONS)
    withdraw.add_argument("--evidence", required=True, help="sha256:<64 hex> reference of the owner decision")
    resume = sub.add_parser("resume", help="Owner: move a delivery that merged a never verified release and "
                                           "halted before the host back to verification (one transaction)")
    resume.add_argument("--plan", required=True, help="The registered plan id")
    resume.add_argument("--plan-sha256", required=True, dest="plan_sha256",
                        help="The registered plan digest (from status)")
    resume.add_argument("--evidence", required=True, help="sha256:<64 hex> reference of the owner decision")
    resume.add_argument("--document", default=None,
                        help="A typed recovery document (urn:zeus:host-delivery-first-activation:1, "
                             "urn:zeus:host-delivery-consumption-retry:1, -generation-restart:1 or "
                             "-consumption-rearm:1, by its kind); "
                             "--evidence must be sha256 of its canonical JSON")
    for command in (targets, register, tick, run_command, status, withdraw, resume):
        command.add_argument("--lane", default=None, help=LANE_HELP)


def run(args) -> None:
    """INV-HOST-DELIVERY-001: exit 0 only for a completed command; refusals print a code and a type,
    never a plan, a descriptor, a host path, a service name, a PR body, a DSN or a raw exception."""
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


def _refusal(exc: Exception) -> dict:
    """What the CLI prints for a failure: a code and a type, never raw text, a path or a value."""
    from codex_harness.kernel.errors import ContractError

    code = getattr(exc, "reason_code", None)
    if code is None and isinstance(exc, ContractError):
        code = "contract_refused"
    return {"status": "refused", "reason_code": code or "error", "error_type": type(exc).__name__,
            "exit_code": 1}


def _execute(service, args) -> dict:
    from codex_harness.composition import cli_host_delivery as composition
    from codex_harness.delivery.domain.host_delivery import (
        FAILED_OUTCOMES,
        RECOVERY_CONSUMPTION_REARM,
        RECOVERY_CONSUMPTION_RETRY,
        RECOVERY_GENERATION_RESTART,
        DeliveryRefused,
    )

    command = args.delivery_command
    lane_id = getattr(args, "lane", None)
    # Without `--lane` every command is exactly what it was: the control store and its workspace.
    route = None if lane_id is None else composition.resolve_lane(service, lane_id)
    store = service.store if route is None else route["store"]
    routed = {} if route is None else {"lane": route["lane"]["id"]}
    if command == "register-targets":
        document = json.loads(Path(args.file).read_text("utf-8"))
        return {**composition.host_delivery_owners(store, service.org).registry.register_targets(document), **routed,
                "exit_code": 0}
    if command == "register":
        repository = (str(composition._git(service).repository) if route is None
                      else route["lane"]["repository"])
        loaded = composition.load_plan(repository, args.revision, args.path)
        receipt = composition.host_delivery_owners(store, service.org).registry.register(loaded["plan"], loaded["pin"])
        return {**receipt, **routed, "bytes": loaded["bytes"], "exit_code": 0}
    if command == "status":
        projection = composition.host_delivery_owners(
            store, service.org,
            enabled=composition.configured_enabled(composition._settings())).registry.status(args.plan)
        return {**projection, **routed,
                "exit_code": 0 if projection.get("registered") or args.plan is None else 1}
    observer = composition._observer(service) if route is None else composition._lane_observer(route)
    try:
        git = (composition._git(service) if route is None
               else composition.lane_git(route["lane"], composition._settings()))
        delivery = composition.controller(service, observer=observer, git=git, store=store)
        if command == "withdraw":
            # The configured opt-in is not consulted: withdrawal publishes, merges and switches
            # nothing, and it is exactly how a held controller retires stale work.
            return {**delivery.withdrawal.withdraw(args.plan, args.plan_sha256, args.reason, args.evidence), **routed,
                    "exit_code": 0}
        if command == "resume":
            # Like withdrawal, resume is a store transition only: it publishes, merges, verifies and
            # switches nothing, and the configured opt-in is not consulted.
            if getattr(args, "document", None) is not None:
                # INV-HOST-DELIVERY-FIRST-ACTIVATION-001: the owner's first-activation binding.
                document = composition.read_json(Path(args.document))
                if document is None:
                    raise DeliveryRefused("first_activation_document_unreadable", "document")
                # The document's own `kind` selects the typed recovery; its validator refuses the rest. The
                # generation restart is the ONE kind with a host effect: the target's own guarded start of the
                # SAME bound descriptor, under the single release fence (INV-HOST-DELIVERY-FIRST-ACTIVATION-001).
                kind = document.get("kind") if isinstance(document, dict) else None
                owner = getattr(delivery.recovery, {RECOVERY_CONSUMPTION_RETRY: "resume_consumption_retry",
                                                    RECOVERY_CONSUMPTION_REARM: "resume_consumption_rearm",
                                                    RECOVERY_GENERATION_RESTART: "resume_generation_restart"}.get(
                                                        kind, "resume_first_activation"))
                return {**owner(args.plan, args.plan_sha256, document, args.evidence), **routed, "exit_code": 0}
            return {**delivery.resumption.resume(args.plan, args.plan_sha256, args.evidence), **routed, "exit_code": 0}
        if command == "tick":
            result = delivery.controller.tick(args.plan)
            return {**result, **routed, "exit_code": 1 if result["outcome"] in FAILED_OUTCOMES else 0}
        return {**composition.run_loop(delivery.controller, verifier=delivery.verification.verifier,
                                       once=bool(args.once), interval=args.interval,
                                       max_ticks=args.max_ticks), **routed, "exit_code": 0}
    finally:
        if observer is not None:
            observer.close()
